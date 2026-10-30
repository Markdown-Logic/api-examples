// Run one server-side report scenario, or start the local webhook listener.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/signal"
)

// run keeps command selection separate from the scenario and listener implementations.
func run(ctx context.Context, args []string) error {
	if len(args) != 1 {
		return errors.New("usage: bash go/run.sh 01|02|03|04|05|06|webhook")
	}
	if args[0] == "webhook" {
		return listenForWebhooks(ctx)
	}
	return scenario(ctx, args[0])
}

func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt)
	defer cancel()
	if err := run(ctx, os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
