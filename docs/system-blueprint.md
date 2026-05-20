# AutoHelp.uz System Blueprint (MVP -> Full)

## 1) Product Scope
Platform participants:
- Driver (client): creates order, tracks status, rates service
- Dispatcher: accepts new order, assigns master, supervises SLA
- Master: accepts/rejects assignment, updates work status, submits completion data
- Admin: monitors KPIs, users, districts, audit logs, exports

## 2) Domain Model (Core)
Core entities:
- `users` (drivers): telegram_id, name, phone, language
- `staff` (dispatcher/admin): telegram_id, role, permissions
- `masters`: telegram_id, phone, district, shift status, rating
- `orders`: client_id, issue_type, issue_note, geo_point, address_hint, status, assignee
- `order_status_history`: state transition audit
- `payments`: order_id, amount, confirmation metadata
- `reviews`: order_id, score, comment
- `districts`: service boundaries and geo polygons
- `audit_logs`: security and operations trail

## 3) Status Lifecycle
Recommended lifecycle:
- `NEW`
- `ASSIGNED`
- `ACCEPTED`
- `ON_THE_WAY`
- `ARRIVED`
- `IN_PROGRESS`
- `COMPLETED`
- `CANCELLED`
- `REJECTED`

Enforcement rules:
- only dispatcher can move `NEW -> ASSIGNED`
- only assigned master can move `ASSIGNED -> ACCEPTED/REJECTED`
- status changes are append-only in `order_status_history`

## 4) Driver Quick Registration Flow
Implemented flow in this starter:
1. Driver selects issue type
2. Driver shares phone (`request_contact`)
3. Driver shares location (`request_location`)
4. Driver confirms request
5. Dispatcher receives alert with order summary + map URL

## 5) Reliability & 24/7 Operations
Operational principles:
- Stateless app containers, state in PostgreSQL + Redis
- Graceful restarts with `unless-stopped`
- Scheduler isolated in separate process/container
- Structured logs and alerting hooks
- Daily backup policy + restore drills

Mandatory SLO targets (recommended):
- API uptime >= 99.9%
- P95 dispatcher notification latency <= 5s
- No data loss on single container failure

## 6) Security Baseline
- Strict allowlist for staff telegram IDs
- Secrets only via `.env` / secret manager (never in git)
- Web/admin auth with 2FA (phase-2)
- Rate limiting / anti-spam middleware
- Full audit logs for sensitive operations
- TLS termination at reverse proxy layer

## 7) Delivery Plan
Phase 1 (MVP, 1-2 weeks):
- Driver order creation
- Dispatcher assignment
- Master status updates
- Admin basic KPI in bot

Phase 2 (Full System):
- Web admin panel
- Excel exports and advanced filters
- Media proof workflow
- District-level analytics and leaderboards

Phase 3 (Scale):
- Smart auto-assignment
- Payment integrations
- Mobile app/API extension
- CRM integration
