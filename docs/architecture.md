# Architecture

React polls Flask arrivals every 30 seconds after the previous request completes. Flask returns normalized JSON and caches demo responses per station for 30 seconds. Cache TTL is configurable; frontend polling currently lives in useArrivals.js. Failed refreshes retain the previous arrivals with an error and their original timestamp.

The MTA integration boundary is services/mta_client.py, connected through transit_service.py at application initialization. Demo mode uses four development stations. Live mode loads the generated catalog once, then uses the adapter for arrivals/alerts. A CachedFeedSession caches only validated responses by upstream URL for 30 seconds by default, coalescing concurrent calls within a process. The adapter revalidates freshness on each use and normalizes current predictions. Failures return 503 without substituting demo data. Timeout and freshness thresholds are configurable. Frontend demo labels remain a separate integration task.

Flask routes validate HTTP input; services own business logic. Transit responses stay in the process-local cache rather than Firestore. For multiple workers or replicas, use a shared cache and a coordinated feed fetcher to avoid repeated upstream requests. This is a development server, not production serving infrastructure.

Firebase Auth runs in React. React sends an ID token in Authorization: Bearer. Flask verifies the token (including revocation), derives uid, and accesses only that user's Firestore favorites. Frontend SDK does not access Firestore directly; rules deny client database access. The Admin SDK bypasses these rules, so route authorization is required.

Persistent schema: users/{uid}/favorites/{station_id} with station_id:string. Future preferences can live in a dedicated user document. Use station IDs consistently across frontend, API, and data imports.
