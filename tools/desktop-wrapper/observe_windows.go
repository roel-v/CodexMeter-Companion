package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/gorilla/websocket"
)

var incompatible = errors.New("incompatible status protocol")

type observer struct {
	conn *websocket.Conn
	seq  int
}

func (o *observer) call(method string, params any, result any) error {
	o.seq++
	if err := o.conn.WriteJSON(map[string]any{"id": o.seq, "method": method, "params": params}); err != nil {
		return err
	}
	for {
		// The client never subscribes to a thread or requests its turns.
		var msg struct {
			ID     int
			Method string
			Result json.RawMessage
			Error  *struct{ Code int }
		}
		if err := o.conn.ReadJSON(&msg); err != nil {
			return err
		}
		if msg.Method != "" || msg.ID != o.seq {
			continue
		}
		if msg.Error != nil {
			if msg.Error.Code == -32601 || msg.Error.Code == -32602 {
				return incompatible
			}
			return errors.New("status temporarily unavailable")
		}
		if len(msg.Result) == 0 || string(msg.Result) == "null" || json.Unmarshal(msg.Result, result) != nil {
			return incompatible
		}
		return nil
	}
}

func readEndpoint(ctx context.Context, path string, roots map[string]bool, states map[string]string) error {
	c, err := connect(ctx, path)
	if err != nil {
		return err
	}
	defer c.Close()
	deadline, _ := ctx.Deadline()
	c.SetReadDeadline(deadline)
	c.SetWriteDeadline(deadline)
	c.SetReadLimit(8 << 20)
	o := observer{conn: c}
	var init struct{ UserAgent string }
	err = o.call("initialize", map[string]any{"clientInfo": map[string]string{"name": "codexmeter", "version": "1"}, "capabilities": map[string]bool{"experimentalApi": true}}, &init)
	if err != nil {
		return err
	}
	if init.UserAgent == "" {
		return incompatible
	}
	if err = c.WriteJSON(map[string]string{"method": "initialized"}); err != nil {
		return err
	}
	params := map[string]any{"limit": 100}
	cursors := map[string]bool{}
	for {
		var page struct {
			Data       *[]string
			NextCursor *string
		}
		if err = o.call("thread/loaded/list", params, &page); err != nil {
			return err
		}
		if page.Data == nil {
			return incompatible
		}
		for _, tid := range *page.Data {
			if !roots[tid] {
				continue
			}
			var res struct {
				Thread struct {
					ID        string
					Ephemeral *bool
					Status    struct {
						Type        string
						ActiveFlags *[]string
					}
				}
			}
			if err = o.call("thread/read", map[string]any{"threadId": tid, "includeTurns": false}, &res); err != nil {
				return err
			}
			t := res.Thread
			if t.ID != tid || t.Ephemeral == nil {
				return incompatible
			}
			if *t.Ephemeral {
				continue
			}
			switch t.Status.Type {
			case "idle", "notLoaded", "systemError":
				continue
			case "active":
				if t.Status.ActiveFlags == nil {
					return incompatible
				}
				state := "running"
				for _, f := range *t.Status.ActiveFlags {
					switch f {
					case "waitingOnApproval", "waitingOnUserInput":
						state = "waiting"
					default:
						return incompatible
					}
				}
				if previous := states[tid]; previous != "" && previous != state {
					return errors.New("inconsistent owners")
				}
				states[tid] = state
			default:
				return incompatible
			}
		}
		if page.NextCursor == nil {
			return nil
		}
		cursor := *page.NextCursor
		if cursor == "" || cursors[cursor] {
			return incompatible
		}
		cursors[cursor] = true
		params["cursor"] = cursor
	}
}

// Ignore abandoned sockets after a Windows shutdown. PID and executable
// identity must both match a live adapter before the endpoint counts.
func liveAdapter(name, prefix, suffix string) bool {
	id, err := strconv.ParseUint(strings.TrimSuffix(strings.TrimPrefix(name, prefix), suffix), 10, 32)
	if err != nil {
		return false
	}
	image, err := processImage(uint32(id))
	if err != nil {
		return false
	}
	self, err := os.Executable()
	return err == nil && strings.EqualFold(filepath.Clean(image), filepath.Clean(self))
}

func snapshot() error {
	var roots []string
	if err := json.NewDecoder(os.Stdin).Decode(&roots); err != nil {
		return err
	}
	keep := map[string]bool{}
	for _, id := range roots {
		keep[id] = true
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	paths, err := filepath.Glob(filepath.Join(home(), "app-server-control", "meter-*.sock"))
	if err != nil {
		return err
	}
	states := map[string]string{}
	endpoints := 0
	health := "inactive"
	fallback, _ := filepath.Glob(filepath.Join(home(), "meter-fallback-*.flag"))
	for _, f := range fallback {
		if liveAdapter(filepath.Base(f), "meter-fallback-", ".flag") {
			return json.NewEncoder(os.Stdout).Encode(map[string]string{"health": "listener_failed"})
		}
	}
	for _, p := range paths {
		if !liveAdapter(filepath.Base(p), "meter-", ".sock") {
			continue
		}
		endpoints++
		if err = readEndpoint(ctx, p, keep, states); err != nil {
			health = "connection"
			if errors.Is(err, incompatible) {
				health = "protocol"
			}
			return json.NewEncoder(os.Stdout).Encode(map[string]string{"health": health})
		}
	}
	if endpoints > 0 {
		health = "ok"
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"health": health, "states": states})
}
