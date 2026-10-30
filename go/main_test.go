package main

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestOrigin(t *testing.T) {
	for _, bad := range []string{"http://example.com", "https://user:pass@example.com", "https://example.com/path", "https://example.com?q=secret", "https://example.com#secret"} {
		if _, err := origin(bad); err == nil {
			t.Errorf("accepted unsafe origin: %s", bad)
		}
	}
	for _, good := range []string{"https://api.markdownlogic.com", "http://127.0.0.1:1234", "http://localhost:1234", "http://[::1]:1234"} {
		if _, err := origin(good); err != nil {
			t.Error(err)
		}
	}
}
func TestRetryWait(t *testing.T) {
	now := time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		value   string
		attempt int
		want    time.Duration
		ok      bool
	}{{"0", 0, 0, true}, {"2", 0, 2 * time.Second, true}, {"120", 0, 0, false}, {"2147483648", 0, 0, false}, {"999999999999999999999999999999999999", 0, 0, false}, {"", 1, 2 * time.Second, true}, {now.Add(2 * time.Second).Format(http.TimeFormat), 0, 2 * time.Second, true}} {
		d, err := retryWait(tc.value, tc.attempt, now)
		if (err == nil) != tc.ok || tc.ok && (d < tc.want || d > tc.want+200*time.Millisecond || d > 5*time.Second) {
			t.Errorf("%#v: wait=%s err=%v", tc, d, err)
		}
	}
}
func TestWebhookSignature(t *testing.T) {
	raw := []byte(`{"id":"event-1","type":"document.updated","data":{"object":{"logicalName":"café.md"}}}`)
	now := time.Unix(1800000000, 0)
	secret := "whsec_synthetic"
	signature := func(body []byte, stamp int64) string {
		m := hmac.New(sha256.New, []byte(secret))
		fmt.Fprintf(m, "%d.", stamp)
		m.Write(body)
		return fmt.Sprintf("t=%d,v1=%s", stamp, hex.EncodeToString(m.Sum(nil)))
	}
	if !verifySignature(signature(raw, now.Unix())+",v1="+strings.Repeat("0", 64), raw, secret, now) {
		t.Fatal("valid rotation signature rejected")
	}
	for _, h := range []string{"", signature(raw, now.Unix()-301), signature(raw, now.Unix()+301), "t=1800000000,v1=bad"} {
		if verifySignature(h, raw, secret, now) {
			t.Errorf("accepted invalid signature %s", h)
		}
	}
	if verifySignature(signature(raw, now.Unix()), append(raw, ' '), secret, now) {
		t.Fatal("accepted changed raw bytes")
	}
}
func TestReadRetryWriteSingleAttempt(t *testing.T) {
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests++
		w.Header().Set("Retry-After", "0")
		w.Header().Set("x-request-id", "req-123")
		w.WriteHeader(429)
		io.WriteString(w, `{"code":"RATE_LIMITED","error":"do-not-log-secret"}`)
	}))
	defer server.Close()
	a := api{base: server.URL, token: "synthetic", client: client()}
	_, err := a.request(context.Background(), "GET", "/", nil)
	if requests != 3 || err == nil || strings.Contains(err.Error(), "do-not-log-secret") || !strings.Contains(err.Error(), "req-123") {
		t.Fatalf("GET requests=%d err=%v", requests, err)
	}
	requests = 0
	_, err = a.request(context.Background(), "PUT", "/", map[string]any{"content": "synthetic"})
	if requests != 1 || err == nil {
		t.Fatalf("write requests=%d err=%v", requests, err)
	}
}
func TestWebhookInboxAndDedupe(t *testing.T) {
	t.Setenv("MDLOGIC_STATE_DIR", t.TempDir())
	t.Setenv("MDLOGIC_WEBHOOK_SECRET", "whsec_test")
	raw := []byte(`{"id":"evt-1","type":"document.updated","data":{"object":{"id":"doc-1"}}}`)
	stamp := time.Now().Unix()
	m := hmac.New(sha256.New, []byte("whsec_test"))
	fmt.Fprintf(m, "%d.", stamp)
	m.Write(raw)
	sig := fmt.Sprintf("t=%d,v1=%x", stamp, m.Sum(nil))
	handler, err := webhookHandler()
	if err != nil {
		t.Fatal(err)
	}
	send := func(header string) int {
		r := httptest.NewRequest("POST", "/webhook", strings.NewReader(string(raw)))
		r.Header.Set("MDL-Signature", header)
		r.Header.Set("MDL-Event-Id", "evt-1")
		r.Header.Set("MDL-Event-Type", "document.updated")
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		return w.Code
	}
	if send("invalid") != 401 || send(sig) != 202 || send(sig) != 200 {
		t.Fatal("signature/dedup status mismatch")
	}
	files, err := filepath.Glob(filepath.Join(os.Getenv("MDLOGIC_STATE_DIR"), "inbox", "*.json"))
	if err != nil || len(files) != 1 {
		t.Fatalf("inbox=%v err=%v", files, err)
	}
	info, _ := os.Stat(files[0])
	if info.Mode().Perm()&0077 != 0 {
		t.Fatal("inbox is not private")
	}
}

func TestLargeExportRefusesPartialResult(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(200)
		_, _ = w.Write(bytes.Repeat([]byte("x"), (20<<20)+1))
	}))
	defer server.Close()
	a := api{base: server.URL, token: "synthetic", client: client()}
	raw, err := a.request(context.Background(), "GET", "/renders/html", nil)
	if err == nil || raw != nil {
		t.Fatal("oversized export should fail without returning partial bytes")
	}
}
func TestCreatePendingMarkerBlocksRepeat(t *testing.T) {
	t.Setenv("MDLOGIC_STATE_DIR", t.TempDir())
	if err := pending("02", "/api/v1/projects/project-1/artifacts", object{"content": "original synthetic report"}); err != nil {
		t.Fatal(err)
	}
	if err := pending("02", "/api/v1/projects/project-1/artifacts", object{"content": "original synthetic report"}); err == nil {
		t.Fatal("uncertain create was allowed to repeat")
	}
	raw, err := os.ReadFile(filepath.Join(os.Getenv("MDLOGIC_STATE_DIR"), "pending-02.json"))
	if err != nil || !strings.Contains(string(raw), "original synthetic report") {
		t.Fatal("original operation was not preserved")
	}
	if err := done("02"); err != nil {
		t.Fatal(err)
	}
	if err := pending("02", "/api/v1/projects/project-1/artifacts", object{"content": "original synthetic report"}); err != nil {
		t.Fatal(err)
	}
}
func TestMutationBodyTimeoutIsUncertainAndSingleAttempt(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		w.WriteHeader(200)
		w.(http.Flusher).Flush()
		<-r.Context().Done()
	}))
	defer server.Close()
	c := client()
	c.Timeout = 20 * time.Millisecond
	a := api{base: server.URL, token: "synthetic", client: c}
	_, err := a.request(context.Background(), "PUT", "/", object{"content": "synthetic"})
	if err == nil || !strings.Contains(err.Error(), "uncertain") || requests.Load() != 1 {
		t.Fatalf("requests=%d error=%v", requests.Load(), err)
	}
}
