import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// Placeholder — device/tunnel/DNS/route settings come in the next pass.
class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const SafeArea(
      child: Center(
        child: Text(
          'تنظیمات — به‌زودی',
          style: TextStyle(color: AppColors.textSecondary, fontSize: 15),
        ),
      ),
    );
  }
}
