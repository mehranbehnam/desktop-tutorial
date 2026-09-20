import 'package:flutter/material.dart';

/// Colors and text styles for the whole app. Kept in one place because the
/// home screen (globe, graph, stat tiles) all need to agree on the same
/// "dark, glowing sky" palette for the glow effects to read as one scene
/// instead of a pile of separately-tinted widgets.
class AppColors {
  AppColors._();

  static const background = Color(0xFF060B16);
  static const surface = Color(0xFF0E1626);
  static const surfaceRaised = Color(0xFF141F33);
  static const border = Color(0xFF223049);

  static const globeCore = Color(0xFF1C6FE0);
  static const globeRim = Color(0xFF7EC8FF);
  static const globeShadow = Color(0xFF020610);

  static const accent = Color(0xFF3FA9FF);
  static const accentSoft = Color(0xFF7ED0FF);

  static const textPrimary = Color(0xFFF3F6FB);
  static const textSecondary = Color(0xFF8CA0BE);
  static const textFaint = Color(0xFF4C5E7A);

  static const graphLine = Color(0xFF5AD1C6);
  static const graphFillTop = Color(0x555AD1C6);
  static const graphFillBottom = Color(0x005AD1C6);

  static const success = Color(0xFF37D67A);
}

class AppTheme {
  AppTheme._();

  static ThemeData get dark {
    final base = ThemeData.dark(useMaterial3: true);
    return base.copyWith(
      scaffoldBackgroundColor: AppColors.background,
      colorScheme: base.colorScheme.copyWith(
        primary: AppColors.accent,
        secondary: AppColors.accentSoft,
        surface: AppColors.surface,
      ),
      textTheme: base.textTheme.apply(
        bodyColor: AppColors.textPrimary,
        displayColor: AppColors.textPrimary,
      ),
    );
  }
}
