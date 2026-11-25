package main

import (
	"context"
	"errors"
	"github.com/gorilla/websocket"
	"net"
	"net/http"
	"path/filepath"
	"testing"
	"time"
)

func TestLaunchArguments(t *testing.T) {
	for _, args := range [][]string{{"app-server", "--print-startup-config"}, {"app-server", "proxy"}, {"--version"}, {"app-server", "--listen", "ws://localhost:9000"}, {"app-server", "--future"}, {"-c", "app-server"}} {
		if _, ok := listenArgs(args, "s"); ok {
			t.Fatal(args)
		}
	}
	a, ok := listenArgs([]string{"-c", "a=b", "app-server", "--listen", "stdio://", "--analytics-default-enabled"}, "socket")
	if !ok || a[4] != "unix://socket" || a[1] != "a=b" {
		t.Fatal(a)
	}
}
func TestResolveBundledAcrossUpdates(t *testing.T) {
	for _, version := range []string{"26.1117.4957.0", "28.1.5.0"} {
		app := filepath.Join("C:/Program Files/WindowsApps", "OpenAI.Codex_"+version+"_x64__2p2nqsd0c76g0", "app")
		if desktopCLI(filepath.Join(app, "ChatGPT.exe")) != filepath.Join(app, "resources", "codex.exe") {
			t.Fatal(version)
		}
	}
	if desktopCLI("C:/temp/ChatGPT.exe") != "" {
		t.Fatal("unexpected package")
	}
}
func TestObserveContract(t *testing.T) {
	for _, tc := range []struct {
		flag string
		want string
		bad  bool
	}{{"", "running", false}, {"waitingOnApproval", "waiting", false}, {"waitingOnUserInput", "waiting", false}, {"newFlag", "", true}} {
		t.Run(tc.flag, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "s")
			listener, err := net.Listen("unix", path)
			if err != nil {
				t.Fatal(err)
			}
			server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				up := websocket.Upgrader{}
				c, err := up.Upgrade(w, r, nil)
				if err != nil {
					return
				}
				defer c.Close()
				for {
					var q struct {
						ID     int
						Method string
						Params map[string]any
					}
					if c.ReadJSON(&q) != nil {
						return
					}
					var res any
					switch q.Method {
					case "initialize":
						res = map[string]string{"userAgent": "Codex"}
					case "initialized":
						continue
					case "thread/loaded/list":
						if q.Params["cursor"] == nil {
							res = map[string]any{"data": []string{"background"}, "nextCursor": "p2"}
						} else {
							res = map[string]any{"data": []string{"chat"}}
						}
					case "thread/read":
						if q.Params["includeTurns"] != false || q.Params["threadId"] != "chat" {
							t.Error("unexpected read", q.Params)
							return
						}
						flags := []string{}
						if tc.flag != "" {
							flags = append(flags, tc.flag)
						}
						res = map[string]any{"thread": map[string]any{"id": "chat", "ephemeral": false, "status": map[string]any{"type": "active", "activeFlags": flags}}}
					default:
						t.Error("unexpected method")
						return
					}
					if c.WriteJSON(map[string]any{"id": q.ID, "result": res}) != nil {
						return
					}
				}
			})}
			go server.Serve(listener)
			defer server.Close()
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			got := map[string]string{}
			err = readEndpoint(ctx, path, map[string]bool{"chat": true}, got)
			if errors.Is(err, incompatible) != tc.bad || got["chat"] != tc.want {
				t.Fatal(err, got)
			}
		})
	}
}
