// HTTP calls, authentication and bounded read retries used by the numbered scenarios.
package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// api holds one account's in-memory token and the HTTP client used by a scenario.
type api struct {
	base   string
	token  string
	client *http.Client
}

// client bounds the complete response, including its body, to fifteen seconds.
// Redirects are refused so a bearer token cannot be forwarded to another origin.
func client() *http.Client {
	return &http.Client{
		Timeout: 15 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
}

// retryWait honors Retry-After before adding small positive jitter.
// A server-requested wait over the example budget stops instead of retrying early.
func retryWait(header string, attempt int, now time.Time) (time.Duration, error) {
	delay := time.Duration(1<<attempt) * time.Second
	if retryAfterSeconds.MatchString(header) {
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

var retryAfterSeconds = regexp.MustCompile(`^[0-9]+$`)

var safeField = regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,128}$`)

// safe allows only bounded identifiers in diagnostics; arbitrary response text stays private.
func safe(value string) string {
	if safeField.MatchString(value) {
		return value
	}
	return "unavailable"
}

// responseError pairs a safe request ID with an actionable recovery step.
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

// request retries only explicit GET rate limits, with at most three total attempts.
// A failed mutation can already have committed, so every write is single-attempt.
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

// json requires an object response; malformed mutation responses still need reconciliation.
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

// connect uses an existing access token or exchanges server-side client credentials.
// Client credentials act as their own account; they do not impersonate an end user.
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
	form := url.Values{
		"grant_type":    {"client_credentials"},
		"client_id":     {id},
		"client_secret": {secret},
		"scope":         {"projects:read documents:read documents:write"},
	}
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
