// Authenticate exact webhook bytes before accepting complete events into a private inbox.
package main

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// verifySignature authenticates the exact bytes before JSON parsing or acceptance.
// The five-minute timestamp window limits replay; any v1 value may match during rotation.
func verifySignature(header string, raw []byte, secret string, now time.Time) bool {
	var stamp string
	var candidates []string
	for _, part := range strings.Split(header, ",") {
		part = strings.TrimSpace(part)
		if strings.HasPrefix(part, "t=") && stamp == "" {
			stamp = strings.TrimPrefix(part, "t=")
		}
		if strings.HasPrefix(part, "v1=") {
			candidates = append(candidates, strings.TrimPrefix(part, "v1="))
		}
	}
	t, err := strconv.ParseInt(stamp, 10, 64)
	if err != nil || t <= 0 || t < now.Unix()-300 || t > now.Unix()+300 {
		return false
	}
	mac := hmac.New(sha256.New, []byte(secret))
	// Authenticate the timestamp text exactly as supplied, not a reformatted integer.
	// Parsing above is only for the freshness check.
	mac.Write([]byte(stamp + "."))
	mac.Write(raw)
	expected := mac.Sum(nil)
	for _, value := range candidates {
		got, err := hex.DecodeString(value)
		if err == nil && hmac.Equal(expected, got) {
			return true
		}
	}
	return false
}

// webhookHandler validates identity headers against the signed envelope and accepts
// each event ID once. Delivery attempt IDs are deliberately not deduplication keys.
func webhookHandler() (http.Handler, error) {
	secret, err := required("MDLOGIC_WEBHOOK_SECRET")
	if err != nil {
		return nil, err
	}
	inbox := filepath.Join(stateDir(), "inbox")
	if err = privateDir(inbox); err != nil {
		return nil, err
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" || r.URL.Path != "/webhook" {
			http.Error(w, "not found", 404)
			return
		}
		raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<20))
		if err != nil {
			http.Error(w, "body too large or incomplete", 413)
			return
		}
		if !verifySignature(r.Header.Get("MDL-Signature"), raw, secret, time.Now()) {
			http.Error(w, "invalid signature", 401)
			return
		}
		var event struct {
			ID   string `json:"id"`
			Type string `json:"type"`
		}
		if json.Unmarshal(raw, &event) != nil {
			http.Error(w, "invalid event envelope", 400)
			return
		}
		headerType := r.Header.Get("MDL-Event-Type")
		if event.ID == "" || event.Type == "" ||
			event.ID != r.Header.Get("MDL-Event-Id") ||
			(headerType != "" && event.Type != headerType) {
			http.Error(w, "invalid event envelope", 400)
			return
		}
		// Publish a complete, synced inbox file atomically. No placeholder can be mistaken for accepted work.
		digest := sha256.Sum256([]byte(event.ID))
		destination := filepath.Join(inbox, hex.EncodeToString(digest[:])+".json")
		tmp, err := os.CreateTemp(inbox, ".incoming-*")
		if err != nil {
			http.Error(w, "inbox unavailable", 503)
			return
		}
		defer os.Remove(tmp.Name())
		if _, err = tmp.Write(raw); err == nil {
			err = tmp.Sync()
		}
		closeErr := tmp.Close()
		if err != nil || closeErr != nil {
			http.Error(w, "inbox unavailable", 503)
			return
		}
		err = os.Link(tmp.Name(), destination)
		if errors.Is(err, os.ErrExist) {
			w.WriteHeader(200)
			return
		}
		if err != nil {
			http.Error(w, "inbox unavailable", 503)
			return
		}
		if directory, err := os.Open(inbox); err == nil {
			_ = directory.Sync()
			_ = directory.Close()
		}
		w.WriteHeader(202) // Local durable inbox only. Business workers need transactional processing.
	}), nil
}

// listenForWebhooks serves the private inbox until the caller cancels its context.
func listenForWebhooks(ctx context.Context) error {
	handler, err := webhookHandler()
	if err != nil {
		return err
	}
	port, err := strconv.Atoi(env("PORT", "8080"))
	if err != nil || port < 1 || port > 65535 {
		return errors.New("PORT must be 1..65535")
	}
	bind := env("MDLOGIC_WEBHOOK_BIND", "127.0.0.1")
	if bind != "127.0.0.1" && bind != "0.0.0.0" {
		return errors.New("invalid webhook bind address")
	}
	server := &http.Server{
		Addr:              fmt.Sprintf("%s:%d", bind, port),
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		MaxHeaderBytes:    16 << 10,
	}
	go func() {
		<-ctx.Done()
		stop, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		_ = server.Shutdown(stop)
	}()
	fmt.Println("Webhook receiver listening on loopback; authenticated events are saved privately.")
	if err = server.ListenAndServe(); errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	if err != nil {
		return errors.New("could not start local webhook receiver")
	}
	return nil
}
