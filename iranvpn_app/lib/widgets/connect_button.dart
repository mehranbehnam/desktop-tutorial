import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// The big glowing "Connect" circle floating over the globe. A short
/// pulse animation while connecting stands in for real handshake
/// progress until the VPN engine reports actual state.
class ConnectButton extends StatelessWidget {
  const ConnectButton({
    super.key,
    required this.connected,
    required this.connecting,
    required this.onTap,
  });

  final bool connected;
  final bool connecting;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final label = connecting ? 'در حال اتصال…' : (connected ? 'قطع اتصال' : 'اتصال');
    final color = connected ? AppColors.success : AppColors.accent;

    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 300),
        width: 96,
        height: 96,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: RadialGradient(
            colors: [color.withOpacity(0.95), color.withOpacity(0.55)],
          ),
          boxShadow: [
            BoxShadow(color: color.withOpacity(0.45), blurRadius: 28, spreadRadius: 2),
          ],
        ),
        alignment: Alignment.center,
        child: Text(
          label,
          textAlign: TextAlign.center,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 13,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
  }
}
