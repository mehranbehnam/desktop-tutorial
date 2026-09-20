import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// Placeholder — the config/subscription list (import URI, add
/// subscription, ping-sort, etc.) comes in the next pass once the VPN
/// engine is wired in. UI-first per the current milestone.
class ConfigsScreen extends StatelessWidget {
  const ConfigsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const SafeArea(
      child: Center(
        child: Text(
          'لیست کانفیگ‌ها — به‌زودی',
          style: TextStyle(color: AppColors.textSecondary, fontSize: 15),
        ),
      ),
    );
  }
}
