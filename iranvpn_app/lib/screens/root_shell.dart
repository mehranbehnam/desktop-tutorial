import 'dart:async';

import 'package:app_links/app_links.dart';
import 'package:flutter/material.dart';

import '../services/vpn_controller.dart';
import '../theme/app_theme.dart';
import 'configs_screen.dart';
import 'home_screen.dart';
import 'settings_screen.dart';

/// Bottom-nav shell: Home / Configs / Settings, matching the reference
/// app's tab layout. Owns the single [VpnController] instance so Home and
/// Configs share the same live connection state.
class RootShell extends StatefulWidget {
  const RootShell({super.key});

  @override
  State<RootShell> createState() => _RootShellState();
}

class _RootShellState extends State<RootShell> {
  int _index = 0;
  final _vpn = VpnController();
  final _appLinks = AppLinks();
  StreamSubscription<Uri>? _linkSub;

  @override
  void initState() {
    super.initState();
    _vpn.init();
    // hermesvpn://import?url=<encoded config> — sent by the Telegram bot's
    // "📎 اتصال خودکار" link/button so a customer never has to copy-paste
    // their config by hand: tapping it lands here with the config already
    // imported, ready for a single tap on Connect.
    _linkSub = _appLinks.uriLinkStream.listen(_handleIncomingLink, onError: (_) {});
    // The stream above only covers links received while already running —
    // a cold start (app wasn't open yet) needs this instead.
    _appLinks.getInitialAppLink().then((uri) {
      if (uri != null) _handleIncomingLink(uri);
    });
  }

  Future<void> _handleIncomingLink(Uri uri) async {
    if (uri.scheme != 'hermesvpn' || uri.host != 'import') return;
    final configUrl = uri.queryParameters['url'];
    if (configUrl == null || configUrl.isEmpty) return;
    try {
      await _vpn.setConfigFromUrl(configUrl);
      if (!mounted) return;
      setState(() => _index = 0);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('کانفیگ اضافه شد — روی Connect بزن.')),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('لینک نامعتبر بود.')),
      );
    }
  }

  @override
  void dispose() {
    _linkSub?.cancel();
    _vpn.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final screens = [
      HomeScreen(vpn: _vpn),
      ConfigsScreen(vpn: _vpn),
      const SettingsScreen(),
    ];
    return Scaffold(
      body: IndexedStack(index: _index, children: screens),
      bottomNavigationBar: Container(
        decoration: const BoxDecoration(
          color: AppColors.surface,
          border: Border(top: BorderSide(color: AppColors.border, width: 0.6)),
        ),
        child: SafeArea(
          top: false,
          child: NavigationBar(
            selectedIndex: _index,
            onDestinationSelected: (i) => setState(() => _index = i),
            backgroundColor: Colors.transparent,
            indicatorColor: AppColors.accent.withOpacity(0.18),
            height: 60,
            labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
            destinations: const [
              NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home), label: 'Home'),
              NavigationDestination(icon: Icon(Icons.list_alt_outlined), selectedIcon: Icon(Icons.list_alt), label: 'Configs'),
              NavigationDestination(icon: Icon(Icons.settings_outlined), selectedIcon: Icon(Icons.settings), label: 'Settings'),
            ],
          ),
        ),
      ),
    );
  }
}
