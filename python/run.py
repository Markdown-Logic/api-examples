"""Dispatch one report task or the standalone webhook listener.

Run from the repository root so the fixture paths match the other languages.
"""

import json
import sys

from api import Api, ExampleError
from receiver import receive
from scenarios import SCENARIOS
from state import PrivateFiles


def scenario(number):
    """Load private mappings and run exactly the task the caller requested."""
    files = PrivateFiles()
    if number == 'webhook':
        return receive(files.directory)
    if number not in SCENARIOS:
        raise ExampleError('Choose 01..06 or webhook; run from the repository root.')
    state = files.load()
    # Reject mapped creates before even exchanging credentials with the server.
    if number == '01' and state.get('projectId'):
        raise ExampleError('Project is already mapped. Reuse its stable ID.')
    if number == '02' and state.get('documentId'):
        raise ExampleError('Report is already mapped. Use 03 to update it.')
    return SCENARIOS[number](Api(), files, state)


def main():
    """Print safe summaries; never expose raw HTTP responses or private inputs."""
    try:
        if len(sys.argv) != 2:
            raise ExampleError('Choose 01..06 or webhook.')
        result = scenario(sys.argv[1])
        if result is not None:
            print(json.dumps(result))
    except ExampleError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        print(
            'Operation failed. Keep input and private state; reconcile any uncertain '
            'write before retrying.',
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
