import 'package:flutter/material.dart';

import 'screens/root_shell.dart';
import 'theme/app_theme.dart';

void main() {
  runApp(const IranVpnApp());
}

class IranVpnApp extends StatelessWidget {
  const IranVpnApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'IranVPN',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.dark,
      darkTheme: AppTheme.dark,
      themeMode: ThemeMode.dark,
      home: const RootShell(),
    );
  }
}
