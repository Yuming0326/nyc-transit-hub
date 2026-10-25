# Architecture

React polls Flask arrivals every 30 seconds after the previous request completes. Flask returns normalized JSON and caches demo responses per station for 30 seconds. Cache TTL is configurable; frontend polling currently lives in useArrivals.js. Failed refreshes retain the previous arrivals with an error and their original timestamp.

The MTA integration boundary is services/mta_client.py. It is intentionally unimplemented. Do not silently substitute demo data during live outages. Implement configured feed URLs, request timeouts, protobuf decoding, stop mapping, stale-data handling and tests before enabling live mode. The station catalog is a small development subset, not a full directory.

Flask routes validate HTTP input; services own business logic. Transit responses stay in the process-local cache rather than Firestore. For multiple workers or replicas, use a shared cache and a coordinated feed fetcher to avoid repeated upstream requests. This is a development server, not production serving infrastructure.

Firebase Auth runs in React. React sends an ID token in Authorization: Bearer. Flask verifies the token (including revocation), derives uid, and accesses only that user's Firestore favorites. Frontend SDK does not access Firestore directly; rules deny client database access. The Admin SDK bypasses these rules, so route authorization is required.

Persistent schema: users/{uid}/favorites/{station_id} with station_id:string. Future preferences can live in a dedicated user document. Use station IDs consistently across frontend, API, and data imports.
