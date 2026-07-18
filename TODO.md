# TODO

## High Priority

- [x] Project structure and dependencies
- [x] Configuration module
- [x] Logging module
- [x] Database module
- [x] State manager
- [x] Broker layer
- [x] WebSocket manager
- [x] Instrument resolver
- [x] Paper broker
- [x] PnL engine
- [x] Risk manager
- [x] Exit manager
- [x] Strategy runner
- [x] Ratio spread strategy
- [x] Scheduler
- [x] Reports
- [x] Application entry point

## Medium Priority

- [x] Integration tests covering exit / stop-loss money path (see tests/test_exit_flow.py)
- [x] Run `ruff check .` and fix any issues
- [x] Run `mypy .` and fix any type errors
- [x] Run `pytest` and ensure all tests pass
- [x] Integration test covering a full paper trading session (entry → monitor → exit) (see tests/test_full_session.py)

## Low Priority

- [ ] Live trading adapter
- [ ] Telegram alerts
- [ ] Web dashboard
- [ ] PostgreSQL support
- [ ] Docker deployment
- [ ] CI/CD pipeline
