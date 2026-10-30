// Environment configuration shared by the report scenarios and local listener.
package main

import (
	"errors"
	"fmt"
	"net/url"
	"os"
	"strings"
)

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

// origin accepts HTTPS service origins and literal loopback HTTP for local tests.
// Rejecting user info, paths and queries avoids ambiguous targets and leaked credentials.
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
