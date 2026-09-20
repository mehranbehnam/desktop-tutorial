# IranVPN Connect (Flutter app)

Cross-platform (Android + iOS) client app, built alongside the
[Telegram sales/admin bots](../hermes-vpn-bot). This is the UI-first pass:
the home screen (rotating globe, live traffic graph, connect button) is
real and testable; there is no VPN engine wired in yet.

## Status

- ✅ Home screen: rotating wireframe globe (`lib/widgets/rotating_globe.dart`),
  slow "dreamy" plane drift (`lib/widgets/flying_planes.dart`), a live
  traffic graph (`lib/widgets/traffic_graph.dart`) fed by mock data
  (`lib/services/traffic_controller.dart`), connect button, stat tiles,
  bottom nav (Home/Configs/Settings).
- ⬜ Configs screen (subscription import, manual config, ping-sort) — placeholder only.
- ⬜ Settings screen (tunnel/DNS/route settings) — placeholder only.
- ⬜ Real VPN engine — no packet tunneling yet. `TrafficController` generates
  a random walk so the graph/stats have something to animate; swap its
  `_tick()` data source for the real core's stats stream once that's in.

## Next milestone: the VPN engine

Per the plan, this integrates an existing open-source core rather than
writing tunneling from scratch — the standard approach (v2rayNG, Hiddify,
and the reference "HermesVPN Connect" app all do the same):

- **Xray-core** or **sing-box**, compiled to a mobile library (AAR for
  Android via `gomobile bind`; an XCFramework for iOS) — accepts the same
  VLESS/Reality/WS+TLS config JSON the bots already generate
  (`hermes-vpn-bot/bot/xui_client.py:build_vless_link`).
- Android: a `VpnService` implementation that hands packets to the core.
- iOS: a Network Extension (Packet Tunnel Provider) target.
- The bots' subscription URL (`XUIClient.get_sub_url`) is already a
  standard subscription format this app's "Add Subscription" flow can
  consume directly.

## Running it

```bash
flutter pub get
flutter run            # needs a connected device/emulator
flutter test           # widget test for the home screen
flutter analyze
```

No extra setup needed — the app has no non-SDK dependencies yet.
