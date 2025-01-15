import itertools
import threading
import time

import click


class Spinner:
    """A utility class for displaying a spinning progress indicator."""

    def __init__(self):
        self._spinner_chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        self._done = threading.Event()
        self._spinner_thread = None

    def start(self, message: str) -> None:
        """Start displaying the spinner with the given message.

        Args:
            message: The message to display alongside the spinner.
        """
        self._done.clear()
        self._spinner_thread = threading.Thread(target=self._spinner_task, args=(message,), daemon=True)
        self._spinner_thread.start()

    def stop(self, message: str | None = None) -> None:
        """Stop the spinner and optionally display a final message.

        Args:
            message: Optional final message to display. If None, uses the original message.
        """
        self._done.set()
        if self._spinner_thread:
            self._spinner_thread.join()

    def _spinner_task(self, message: str) -> None:
        """Internal method that handles the spinner animation."""
        spinner = itertools.cycle(self._spinner_chars)
        while not self._done.is_set():
            click.echo(f'\r{next(spinner)} {message}', nl=False)
            time.sleep(0.1)
        click.echo(f'\r✓ {message}')

    def __enter__(self) -> 'Spinner':
        """Allows the Spinner to be used as a context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Ensures the spinner is stopped when exiting the context."""
        self.stop()
