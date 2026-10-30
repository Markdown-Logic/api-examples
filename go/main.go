// Small server-side report integration examples. Run one numbered scenario at a time.
package main

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

type object = map[string]any
type state struct {
	ProjectID  string `json:"projectId,omitempty"`
	DocumentID string `json:"documentId,omitempty"`
	Revision   string `json:"revision,omitempty"`
}
type api struct {
	base, token string
	client      *http.Client
}

func env(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}
func required(name string) (string, error) {
	if v := os.Getenv(name); v != "" {
		return v, nil
	}
	return "", fmt.Errorf("set %s before this scenario", name)
}
func origin(value string) (string, error) {
	u, err := url.Parse(value)
	if err != nil || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" || u.RawPath != "" || (u.Path != "" && u.Path != "/") {
		return "", errors.New("configure a canonical API/auth origin without credentials, path, query or fragment")
	}
	local := u.Hostname() == "localhost" || u.Hostname() == "127.0.0.1" || u.Hostname() == "::1"
	if u.Scheme != "https" && !(u.Scheme == "http" && local) {
		return "", errors.New("origins require HTTPS; HTTP is allowed only for literal loopback hosts")
	}
	return strings.TrimSuffix(u.String(), "/"), nil
}
func client() *http.Client {
	return &http.Client{Timeout: 15 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}

// GET retries are deliberately narrow. Mutations, auth failures and uncertain IO never retry.
func retryWait(header string, attempt int, now time.Time) (time.Duration, error) {
	delay := time.Duration(1<<attempt) * time.Second
	if regexp.MustCompile(`^[0-9]+$`).MatchString(header) {
		seconds, err := strconv.ParseUint(header, 10, 64)
		if err != nil || seconds > 5 {
			return 0, errors.New("Retry-After exceeds the five-second example budget; pause and run deliberately later")
		}
		delay = time.Duration(seconds) * time.Second
	} else if when, err := http.ParseTime(header); err == nil {
		delay = when.Sub(now)
		if delay < 0 {
			delay = 0
		}
	}
	if delay > 5*time.Second {
		return 0, errors.New("Retry-After exceeds the five-second example budget; pause and run deliberately later")
	}
	var jitter [1]byte
	if _, err := rand.Read(jitter[:]); err != nil {
		return 0, errors.New("could not choose retry jitter")
	}
	delay += time.Duration(1+int(jitter[0])%200) * time.Millisecond
	if delay > 5*time.Second {
		delay = 5 * time.Second
	}
	return delay, nil
}

var safeField = regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,128}$`)

func safe(value string) string {
	if safeField.MatchString(value) {
		return value
	}
	return "unavailable"
}
func responseError(response *http.Response, raw []byte) error {
	var e struct {
		Code      string `json:"code"`
		RequestID string `json:"requestId"`
		Details   struct {
			Reason string `json:"reason"`
		} `json:"details"`
	}
	_ = json.Unmarshal(raw, &e)
	requestID := response.Header.Get("x-request-id")
	if requestID == "" {
		requestID = e.RequestID
	}
	guidance := "Request stopped; review permissions and current state before another attempt."
	switch response.StatusCode {
	case 401:
		guidance = "Authentication was rejected or revoked. Reconnect; no automatic refresh or retry."
	case 409:
		guidance = "Conflict: read and review the current document; retain input and do not replace the revision guard blindly."
	case 423:
		guidance = "Content is temporarily read-only during ADP conversion. Input is preserved; wait, then review state before retrying deliberately."
	case 429:
		guidance = "Rate limit reached. Read retry budget is exhausted or this mutation is single-attempt; pause before a deliberate attempt."
	}
	return fmt.Errorf("HTTP %d code=%s reason=%s requestId=%s. %s", response.StatusCode, safe(e.Code), safe(e.Details.Reason), safe(requestID), guidance)
}
func (a api) request(ctx context.Context, method, path string, body any) ([]byte, error) {
	var payload []byte
	var err error
	if body != nil {
		payload, err = json.Marshal(body)
		if err != nil {
			return nil, errors.New("request JSON could not be encoded")
		}
	}
	for attempt := 0; attempt < 3; attempt++ {
		req, err := http.NewRequestWithContext(ctx, method, a.base+path, bytes.NewReader(payload))
		if err != nil {
			return nil, errors.New("request configuration is invalid")
		}
		req.Header.Set("Authorization", "Bearer "+a.token)
		if body != nil {
			req.Header.Set("Content-Type", "application/json")
		}
		response, err := a.client.Do(req)
		if err != nil {
			if method == "GET" {
				return nil, errors.New("read timed out, was cancelled or failed; no automatic network retry")
			}
			return nil, errors.New("mutation response is uncertain (timeout, cancellation or network failure); preserve input and reconcile existing state before any new write")
		}
		raw, readErr := io.ReadAll(io.LimitReader(response.Body, (20<<20)+1))
		response.Body.Close()
		if len(raw) > 20<<20 {
			if method == "GET" {
				return nil, errors.New("response exceeds the twenty-MiB example limit; no partial export was saved")
			}
			return nil, errors.New("mutation response exceeds the example limit; reconcile before another write")
		}
		if readErr != nil {
			if method == "GET" {
				return nil, errors.New("read body failed or timed out")
			}
			return nil, errors.New("mutation response body is uncertain; preserve input and reconcile before another write")
		}
		if response.StatusCode >= 200 && response.StatusCode < 300 {
			return raw, nil
		}
		if method == "GET" && response.StatusCode == 429 && attempt < 2 {
			delay, err := retryWait(response.Header.Get("Retry-After"), attempt, time.Now())
			if err != nil {
				return nil, fmt.Errorf("%w; requestId=%s", err, safe(response.Header.Get("x-request-id")))
			}
			timer := time.NewTimer(delay)
			select {
			case <-ctx.Done():
				timer.Stop()
				return nil, errors.New("read retry cancelled")
			case <-timer.C:
			}
			continue
		}
		return nil, responseError(response, raw)
	}
	return nil, errors.New("read retry budget exhausted")
}
func (a api) json(ctx context.Context, method, path string, body any) (object, error) {
	raw, err := a.request(ctx, method, path, body)
	if err != nil {
		return nil, err
	}
	var result object
	if json.Unmarshal(raw, &result) != nil || result == nil {
		return nil, errors.New("unexpected response shape; reconcile any mutation before continuing")
	}
	return result, nil
}
func connect(ctx context.Context) (api, error) {
	base, err := origin(env("MDLOGIC_API_ORIGIN", "https://api.markdownlogic.com"))
	if err != nil {
		return api{}, err
	}
	a := api{base: base, token: os.Getenv("MDLOGIC_TOKEN"), client: client()}
	if a.token != "" {
		return a, nil
	}
	id, err := required("MDLOGIC_CLIENT_ID")
	if err != nil {
		return a, err
	}
	secret, err := required("MDLOGIC_CLIENT_SECRET")
	if err != nil {
		return a, err
	}
	issuer, err := origin(env("MDLOGIC_OAUTH_ISSUER", "https://auth.markdownlogic.com"))
	if err != nil {
		return a, err
	}
	form := url.Values{"grant_type": {"client_credentials"}, "client_id": {id}, "client_secret": {secret}, "scope": {"projects:read documents:read documents:write"}}
	req, err := http.NewRequestWithContext(ctx, "POST", issuer+"/oauth/token", strings.NewReader(form.Encode()))
	if err != nil {
		return a, errors.New("invalid token request")
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	response, err := a.client.Do(req)
	if err != nil {
		return a, errors.New("token exchange failed, timed out or was cancelled; credentials were not retried")
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, 1<<20))
	response.Body.Close()
	if err != nil {
		return a, errors.New("token response failed or timed out")
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return a, responseError(response, raw)
	}
	var token struct {
		AccessToken string `json:"access_token"`
	}
	if json.Unmarshal(raw, &token) != nil || token.AccessToken == "" {
		return a, errors.New("token response did not contain an access token")
	}
	a.token = token.AccessToken
	return a, nil
}
func stateDir() string { return env("MDLOGIC_STATE_DIR", ".local/go") }
func privateDir(path string) error {
	if err := os.MkdirAll(path, 0700); err != nil {
		return err
	}
	return os.Chmod(path, 0700)
}
func save(name string, value any) error {
	raw, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	return saveBytes(name, append(raw, '\n'))
}
func saveBytes(name string, raw []byte) error {
	if err := privateDir(stateDir()); err != nil {
		return errors.New("cannot create private state directory")
	}
	f, err := os.CreateTemp(stateDir(), ".save-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(raw); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(f.Name(), filepath.Join(stateDir(), name))
}
func load() (state, error) {
	var s state
	raw, err := os.ReadFile(filepath.Join(stateDir(), "state.json"))
	if errors.Is(err, os.ErrNotExist) {
		return s, nil
	}
	if err != nil {
		return s, errors.New("cannot read state")
	}
	if json.Unmarshal(raw, &s) != nil {
		return s, errors.New("state is malformed; reconcile before replacing it")
	}
	return s, nil
}
func pending(scenario, path string, body object) error {
	apiOrigin, err := origin(env("MDLOGIC_API_ORIGIN", "https://api.markdownlogic.com"))
	if err != nil {
		return err
	}
	if err := privateDir(stateDir()); err != nil {
		return err
	}
	f, err := os.OpenFile(filepath.Join(stateDir(), "pending-"+scenario+".json"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if errors.Is(err, os.ErrExist) {
		return errors.New("a create operation is pending; reconcile it before removing its marker")
	}
	if err != nil {
		return err
	}
	err = json.NewEncoder(f).Encode(object{"scenario": scenario, "apiOrigin": apiOrigin, "status": "reconcile-before-repeat", "method": "POST", "path": path, "body": body})
	if err == nil {
		err = f.Sync()
	}
	_ = f.Close()
	return err
}
func done(scenario string) error {
	return os.Remove(filepath.Join(stateDir(), "pending-"+scenario+".json"))
}
func field(m object, key string) string { s, _ := m[key].(string); return s }
func child(m object, key string) object { v, _ := m[key].(map[string]any); return v }
func idPath(value string) string        { return url.PathEscape(value) }
func output(v any) error                { return json.NewEncoder(os.Stdout).Encode(v) }

func scenario(ctx context.Context, number string) error {
	if number != "01" && number != "02" && number != "03" && number != "04" && number != "05" && number != "06" {
		return errors.New("choose scenario01..06 or webhook")
	}
	s, err := load()
	if err != nil {
		return err
	}
	if number == "01" && s.ProjectID != "" {
		return errors.New("project already mapped; reuse it rather than creating a duplicate")
	}
	if number == "02" && s.DocumentID != "" {
		return errors.New("report already mapped; use scenario03 to update")
	}
	if number != "01" && number != "06" && s.ProjectID == "" {
		return errors.New("run scenario01 first")
	}
	if number != "01" && number != "02" && number != "06" && s.DocumentID == "" {
		return errors.New("run scenario02 first")
	}

	if number == "05" || number == "06" {
		filename := "share.json"
		if number == "06" {
			filename = "webhook.json"
		}
		if _, err := os.Stat(filepath.Join(stateDir(), filename)); err == nil {
			return errors.New("a private response already exists; inspect and reconcile it before creating another share or webhook")
		} else if !errors.Is(err, os.ErrNotExist) {
			return errors.New("cannot inspect private output before creating")
		}
	}
	a, err := connect(ctx)
	if err != nil {
		return err
	}
	projectPath := "/api/v1/projects/" + idPath(s.ProjectID)
	docPath := projectPath + "/documents/" + idPath(s.DocumentID)
	switch number {
	case "01":
		team, err := required("MDLOGIC_TEAM")
		if err != nil {
			return err
		}
		base := "/api/v1/teams/" + idPath(team) + "/projects"
		body := object{"name": "Report integration example", "mode": "document"}
		if err = pending(number, base, body); err != nil {
			return err
		}
		result, err := a.json(ctx, "POST", base, body)
		if err != nil {
			return err
		}
		s.ProjectID = field(child(result, "project"), "id")
		if s.ProjectID == "" {
			return errors.New("create response missing project ID; reconcile pending create")
		}
		if err = save("state.json", s); err != nil {
			return err
		}
		if err = done(number); err != nil {
			return err
		}
		if _, err = a.json(ctx, "GET", base+"?limit=50&offset=0", nil); err != nil {
			return err
		}
		if _, err = a.json(ctx, "PATCH", "/api/v1/projects/"+idPath(s.ProjectID), object{"name": "Report integration example"}); err != nil {
			return err
		}
		return output(object{"scenario": number, "projectId": s.ProjectID})
	case "02":
		content, err := os.ReadFile(env("MDLOGIC_INPUT", "fixtures/report.md"))
		if err != nil {
			return errors.New("cannot read generated report input")
		}
		if !utf8.Valid(content) {
			return errors.New("report input must be valid UTF-8; original file is preserved")
		}

		body := object{"name": "report.md", "content": string(content), "format": "markdown", "ifNotExists": true}
		if err = pending(number, projectPath+"/artifacts", body); err != nil {
			return err
		}
		result, err := a.json(ctx, "POST", projectPath+"/artifacts", body)
		if err != nil {
			return err
		}
		doc := child(result, "artifact")
		s.DocumentID = field(doc, "id")
		s.Revision = field(doc, "revision")
		if s.DocumentID == "" || s.Revision == "" {
			return errors.New("create response missing stable document ID/revision; reconcile pending create")
		}
		if err = save("state.json", s); err != nil {
			return err
		}
		if err = done(number); err != nil {
			return err
		}
		return output(object{"scenario": number, "documentId": s.DocumentID})
	case "03":
		content, err := os.ReadFile(env("MDLOGIC_INPUT", "fixtures/report-updated.md"))
		if err != nil {
			return errors.New("cannot read updated report input")
		}
		if !utf8.Valid(content) {
			return errors.New("report input must be valid UTF-8; original file is preserved")
		}
		current, err := a.json(ctx, "GET", docPath, nil)
		if err != nil {
			return err
		}
		revision := field(child(current, "document"), "revision")
		if revision == "" {
			return errors.New("live read is missing its revision; stop and review")
		}
		// This synthetic report is already reviewed. A real application must compare edits here.
		result, err := a.json(ctx, "PUT", docPath, object{"content": string(content), "expectedRevision": revision, "changeNote": "Refresh generated report"})
		if err != nil {
			return err
		}
		s.Revision = field(child(result, "document"), "revision")
		if s.Revision == "" {
			return errors.New("write response missing revision; reconcile current document")
		}
		if err = save("state.json", s); err != nil {
			return err
		}
		return output(object{"scenario": number, "documentId": s.DocumentID, "decision": field(result, "decision")})
	case "04":
		page, err := a.json(ctx, "GET", docPath+"/versions?limit=20&offset=0", nil)
		if err != nil {
			return err
		}
		items, validItems := page["items"].([]any)
		_, validMore := page["hasMore"].(bool)
		if !validItems || !validMore {
			return errors.New("malformed history page; export stopped")
		}
		if len(items) > 0 {
			first, _ := items[0].(map[string]any)
			version := field(first, "id")
			if version == "" {
				return errors.New("version result missing ID")
			}
			if _, err = a.json(ctx, "GET", docPath+"/versions/"+idPath(version), nil); err != nil {
				return err
			}
		}
		raw, err := a.request(ctx, "GET", docPath+"/renders/html", nil)
		if err != nil {
			return err
		}
		if err = saveBytes("report.html", raw); err != nil {
			return err
		}
		return output(object{"scenario": number, "versionsOnPage": len(items), "hasMore": page["hasMore"], "exportFile": filepath.Join(stateDir(), "report.html")})
	case "05":
		path, body := docPath+"/shares", object{"expiresInDays": 30}
		if err = pending(number, path, body); err != nil {
			return err
		}
		result, err := a.json(ctx, "POST", path, body)
		if err != nil {
			return err
		}
		if err = save("share.json", result); err != nil {
			return err
		}
		if field(child(result, "share"), "id") == "" || field(child(result, "share"), "url") == "" {
			return errors.New("unusable share response retained privately; reconcile pending operation")
		}
		if err = done(number); err != nil {
			return err
		}
		return output(object{"scenario": number, "shareId": field(child(result, "share"), "id"), "privateFile": filepath.Join(stateDir(), "share.json")})
	case "06":
		team, err := required("MDLOGIC_TEAM")
		if err != nil {
			return err
		}
		destination, err := required("MDLOGIC_WEBHOOK_URL")
		if err != nil {
			return err
		}
		u, err := url.Parse(destination)
		if err != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil {
			return errors.New("webhook destination must be an explicit HTTPS URL without credentials")
		}
		catalogue, err := a.json(ctx, "GET", "/api/v1/webhooks/events", nil)
		if err != nil {
			return err
		}
		available := map[string]bool{}
		catalogueEvents, ok := catalogue["events"].([]any)
		if !ok {
			return errors.New("unexpected event catalogue response; registration stopped")
		}
		for _, v := range catalogueEvents {
			if text, ok := v.(string); ok {
				available[text] = true
			}
		}
		events := []string{"document.created", "document.updated", "project.created", "project.updated", "share.created"}
		for _, event := range events {
			if !available[event] {
				return errors.New("required lifecycle event absent from the live catalogue")
			}
		}
		path, body := "/api/v1/teams/"+idPath(team)+"/webhooks", object{"url": destination, "events": events, "description": "Generated report lifecycle"}
		if err = pending(number, path, body); err != nil {
			return err
		}
		result, err := a.json(ctx, "POST", path, body)
		if err != nil {
			return err
		}
		if err = save("webhook.json", result); err != nil {
			return err
		}
		if field(child(result, "webhook"), "id") == "" || field(result, "secret") == "" {
			return errors.New("unusable webhook response retained privately; reconcile pending operation")
		}
		if err = done(number); err != nil {
			return err
		}
		return output(object{"scenario": number, "webhookId": field(child(result, "webhook"), "id"), "secretFile": filepath.Join(stateDir(), "webhook.json")})
	}
	return errors.New("choose scenario01..06 or webhook")
}

// Verify raw bytes before JSON parsing or durable acceptance. Rotation may supply several v1s.
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
	fmt.Fprintf(mac, "%d.", t)
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
		if json.Unmarshal(raw, &event) != nil || event.ID == "" || event.Type == "" || event.ID != r.Header.Get("MDL-Event-Id") || (r.Header.Get("MDL-Event-Type") != "" && event.Type != r.Header.Get("MDL-Event-Type")) {
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
func run(ctx context.Context, args []string) error {
	if len(args) != 1 {
		return errors.New("usage: bash go/run.sh 01|02|03|04|05|06|webhook")
	}
	if args[0] != "webhook" {
		return scenario(ctx, args[0])
	}
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
	server := &http.Server{Addr: fmt.Sprintf("%s:%d", bind, port), Handler: handler, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 10 * time.Second, MaxHeaderBytes: 16 << 10}
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
func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt)
	defer cancel()
	if err := run(ctx, os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
