from dataclasses import dataclass
from random import Random
from threading import Lock
from time import monotonic, sleep

from app.connectors.base import EventSink
from app.errors import ConnectorCircuitOpen


@dataclass(frozen=True)
class CircuitPermit:
    half_open: bool


class CircuitBreaker:
    """Thread-safe process-local breaker counting failed logical calls."""

    def __init__(self, name: str, threshold: int = 5, open_seconds: float = 30.0, clock=monotonic):
        self.name = name
        self.threshold = threshold
        self.open_seconds = open_seconds
        self.clock = clock
        self._lock = Lock()
        self._state = "closed"
        self._failures = 0
        self._opened_at = 0.0
        self._probe_active = False

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def acquire(self, emit: EventSink | None = None) -> CircuitPermit:
        transition = None
        with self._lock:
            if self._state == "open":
                if self.clock() - self._opened_at < self.open_seconds or self._probe_active:
                    raise ConnectorCircuitOpen()
                self._state = "half_open"
                self._probe_active = True
                transition = ("open", "half_open")
            elif self._state == "half_open":
                raise ConnectorCircuitOpen()
            permit = CircuitPermit(self._state == "half_open")
        if transition and emit:
            emit("connector_circuit_transition", {"upstream": self.name, "from_state": transition[0], "to_state": transition[1]})
        return permit

    def success(self, permit: CircuitPermit, emit: EventSink | None = None) -> None:
        transition = None
        with self._lock:
            previous = self._state
            self._failures = 0
            self._probe_active = False
            self._state = "closed"
            if previous != "closed":
                transition = (previous, "closed")
        if transition and emit:
            emit("connector_circuit_transition", {"upstream": self.name, "from_state": transition[0], "to_state": transition[1]})

    def failure(self, permit: CircuitPermit, emit: EventSink | None = None) -> None:
        transition = None
        with self._lock:
            previous = self._state
            self._probe_active = False
            if permit.half_open:
                self._state = "open"
                self._opened_at = self.clock()
            else:
                self._failures += 1
                if self._failures >= self.threshold:
                    self._state = "open"
                    self._opened_at = self.clock()
            if self._state != previous:
                transition = (previous, self._state)
        if transition and emit:
            emit("connector_circuit_transition", {"upstream": self.name, "from_state": transition[0], "to_state": transition[1]})


class Backoff:
    def __init__(self, sleep_fn=sleep, random_source: Random | None = None):
        self.sleep = sleep_fn
        self.random = random_source or Random()

    def full_jitter(self, attempt: int) -> float:
        return self.random.uniform(0.0, min(1.0, 0.1 * (2 ** (attempt - 1))))
