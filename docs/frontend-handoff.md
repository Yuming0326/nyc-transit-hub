# Frontend handoff

Updated: November 25, 2026  
Owner: Zhaorui  
Branch: `frontend/live-dashboard`

## Implemented in this branch

- Merged the latest `main` foundation without removing the verified account, favorites, refresh, empty-state, or recovery behavior.
- Added shared navigation and responsive page structure for dashboard, transit exploration, journey planning, service/equipment information, and notifications.
- Added subway/bus route discovery, route details, selectable stops/stations, an accessible SVG renderer for official GeoJSON, bus vehicle overlays, and live-arrival detail states.
- Added schedule date/route/direction controls and labels that distinguish scheduled departures from live predictions.
- Added schedule-based journey request UI, journey legs, transfers, same-endpoint-compatible rendering, and explicit no-path/error states.
- Added service-status and equipment panels that keep unknown, partial coverage, reported outage, and unavailable retrieval distinct.
- Added account-aware subscription and in-app notification UI, unread count, read/unread actions, explicit evaluation, and 30-second evaluation while the panel is open.
- Added persistent English/Simplified Chinese language selection. Original MTA notice text is explicitly identified as untranslated.
- Added reusable loading/empty/error/retry handling, request timeouts, request cleanup, stale-response guards, keyboard-operable map points, focus styles, reduced-motion handling, and mobile layout.

## Integration status

The frontend consumes the contracts in `docs/api-contract.md`; it does not fabricate successful data when an endpoint is absent. The transit catalog/map/bus/schedule/journey endpoints are implemented on `feature/transit-data-foundation` but are not yet in `main` at the time of this handoff. Status, equipment, favorites-v2, subscriptions, and notification endpoints still depend on Zachary's backend work. Until those branches are integrated, the corresponding panels intentionally render an explicit API error with retry controls.

The existing station-only favorites UI continues to use the implemented `/api/favorites` contract. Typed bus-stop/route saves must not replace it until `/api/v2/favorites` is integrated and its migration behavior is verified.

## Verification

Run from `frontend/`:

```bash
npm ci
npm test
npm run build
```

Observed locally on November 25, 2026:

- `npm test`: 4/4 passing.
- `npm run build`: successful Vite production build.
- Browser inspection: English/Chinese selection persists; all primary navigation views render; no JavaScript console errors.
- Responsive inspection: 390×844 viewport had no horizontal document overflow; keyboard-visible controls and map points are present.

These checks are local frontend evidence, not deployed feature verification. Full live and account workflows remain subject to the relevant backend merges, Firebase configuration, and hosted redeployment.
