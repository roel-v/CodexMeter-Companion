// CodexMeter's optional Windows Desktop CLI adapter.
package main

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"

	"github.com/gorilla/websocket"
)

var kernel = syscall.NewLazyDLL("kernel32.dll")
var queryImage = kernel.NewProc("QueryFullProcessImageNameW")

func processImage(pid uint32) (string, error) {
	h, err := syscall.OpenProcess(0x1000, false, pid)
	if err != nil {
		return "", err
	}
	defer syscall.CloseHandle(h)
	buf := make([]uint16, 32768)
	n := uint32(len(buf))
	ok, _, err := queryImage.Call(uintptr(h), 0, uintptr(unsafe.Pointer(&buf[0])), uintptr(unsafe.Pointer(&n)))
	if ok == 0 {
		return "", err
	}
	return syscall.UTF16ToString(buf[:n]), nil
}

func desktopCLI(image string) string {
	app := filepath.Dir(image)
	pkg := strings.ToLower(filepath.Base(filepath.Dir(app)))
	if !strings.EqualFold(filepath.Base(image), "ChatGPT.exe") || !strings.EqualFold(filepath.Base(app), "app") ||
		!strings.HasPrefix(pkg, "openai.codex_") || !strings.HasSuffix(pkg, "__2p2nqsd0c76g0") {
		return ""
	}
	return filepath.Join(app, "resources", "codex.exe")
}

func resolve() (string, bool, error) {
	snap, err := syscall.CreateToolhelp32Snapshot(syscall.TH32CS_SNAPPROCESS, 0)
	if err == nil {
		defer syscall.CloseHandle(snap)
		parents := map[uint32]uint32{}
		var e syscall.ProcessEntry32
		e.Size = uint32(unsafe.Sizeof(e))
		for err = syscall.Process32First(snap, &e); err == nil; err = syscall.Process32Next(snap, &e) {
			parents[e.ProcessID] = e.ParentProcessID
		}
		for p, n := uint32(os.Getppid()), 0; p != 0 && n < 24; p, n = parents[p], n+1 {
			path, _ := processImage(p)
			if cli := desktopCLI(path); cli != "" {
				if _, err = os.Stat(cli); err == nil {
					return cli, true, nil
				}
			}
		}
	}
	// A caller outside Desktop (or a changed process layout) gets the registered
	// package's stock CLI. Never search PATH for our own replacement.
	ps := filepath.Join(os.Getenv("SystemRoot"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	c := exec.Command(ps, "-NoProfile", "-NonInteractive", "-Command", "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); (Get-AppxPackage -Name OpenAI.Codex | Where-Object PackageFamilyName -eq 'OpenAI.Codex_2p2nqsd0c76g0' | Select-Object -First 1).InstallLocation")
	b, err := c.Output()
	if err != nil {
		return "", false, err
	}
	root := strings.TrimSpace(string(b))
	if !filepath.IsAbs(root) {
		return "", false, errors.New("Desktop package not found")
	}
	cli := filepath.Join(root, "app", "resources", "codex.exe")
	_, err = os.Stat(cli)
	return cli, false, err
}

// Only adapt a normal server launch. CLI commands, preflight, explicitly
// selected transports and future unknown options keep their native behaviour.
func listenArgs(args []string, socket string) ([]string, bool) {
	out := append([]string{}, args...)
	server := false
	listen := -1
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "-c", "--config", "--enable", "--disable":
			i++
			if i == len(args) {
				return nil, false
			}
		case "app-server":
			if server {
				return nil, false
			}
			server = true
		case "--analytics-default-enabled":
		case "--listen":
			if i+1 >= len(args) || args[i+1] != "stdio://" || listen != -1 {
				return nil, false
			}
			i++
			listen = i
		default:
			return nil, false
		}
	}
	if !server {
		return nil, false
	}
	if listen < 0 {
		out = append(out, "--listen", "unix://"+socket)
	} else {
		out[listen] = "unix://" + socket
	}
	return out, true
}

func home() string {
	if p := os.Getenv("CODEX_HOME"); p != "" {
		return p
	}
	p, _ := os.UserHomeDir()
	return filepath.Join(p, ".codex")
}
func connect(ctx context.Context, path string) (*websocket.Conn, error) {
	d := websocket.Dialer{HandshakeTimeout: 2 * time.Second, NetDialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", path)
	}}
	conn, _, err := d.DialContext(ctx, "ws://localhost/", nil)
	return conn, err
}

func toDesktop(c *websocket.Conn) error {
	for {
		typ, r, err := c.NextReader()
		if err != nil {
			return err
		}
		if typ != websocket.TextMessage {
			return errors.New("unexpected binary RPC")
		}
		if _, err = io.Copy(os.Stdout, r); err != nil {
			return err
		}
		if _, err = os.Stdout.Write([]byte{'\n'}); err != nil {
			return err
		}
	}
}
func fromDesktop(c *websocket.Conn) error {
	r := bufio.NewReaderSize(os.Stdin, 65536)
	for {
		w, err := c.NextWriter(websocket.TextMessage)
		if err != nil {
			return err
		}
		for {
			line, more, err := r.ReadLine()
			if err != nil {
				return err
			}
			if _, err = w.Write(line); err != nil {
				return err
			}
			if !more {
				break
			}
		}
		if err = w.Close(); err != nil {
			return err
		}
	}
}

func availableSocket(cli string, args []string, path string) (bool, error) {
	cmd := exec.Command(cli, args...)
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		return false, err
	}
	job, err := ownServer(cmd.Process.Pid)
	if err != nil {
		cmd.Process.Kill()
		cmd.Wait()
		return false, err
	}
	defer syscall.CloseHandle(syscall.Handle(job))
	exited := make(chan error, 1)
	go func() { exited <- cmd.Wait(); close(exited) }()
	defer func() { cmd.Process.Kill(); <-exited; os.Remove(path) }()
	deadline := time.Now().Add(8 * time.Second)
	var c *websocket.Conn
	for time.Now().Before(deadline) {
		select {
		case <-exited:
			return false, errors.New("Codex rejected private listener")
		default:
		}
		ctx, cancel := context.WithDeadline(context.Background(), deadline)
		var err error
		c, err = connect(ctx, path)
		cancel()
		if err == nil {
			break
		}
		time.Sleep(60 * time.Millisecond)
	}
	if c == nil {
		return false, errors.New("private socket unavailable")
	}
	defer c.Close()
	done := make(chan error, 2)
	go func() { done <- fromDesktop(c) }()
	go func() { done <- toDesktop(c) }()
	select {
	case err := <-exited:
		return true, err
	case err := <-done:
		if errors.Is(err, io.EOF) {
			err = nil
		}
		return true, err
	}
}

func run() error {
	args := os.Args[1:]
	if len(args) == 1 && args[0] == "--meter-snapshot" {
		return snapshot()
	}
	cli, desktop, err := resolve()
	if err != nil {
		return err
	}
	path := filepath.Join(home(), "app-server-control", fmt.Sprintf("meter-%d.sock", os.Getpid()))
	if adapted, ok := listenArgs(args, path); desktop && ok {
		// Windows AF_UNIX paths are limited to 107 bytes. Fail back before
		// consuming any Desktop RPC if this package cannot start the listener.
		if started, err := availableSocket(cli, adapted, path); started {
			return err
		}
		flag := filepath.Join(home(), fmt.Sprintf("meter-fallback-%d.flag", os.Getpid()))
		if os.WriteFile(flag, nil, 0600) == nil {
			defer os.Remove(flag)
		}
	}
	cmd := exec.Command(cli, args...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func main() {
	if err := run(); err != nil {
		var status *exec.ExitError
		if errors.As(err, &status) {
			os.Exit(status.ExitCode())
		}
		fmt.Fprintln(os.Stderr, "CodexMeter: Desktop CLI or local status connection unavailable")
		os.Exit(1)
	}
}
