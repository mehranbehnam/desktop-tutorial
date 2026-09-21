import 'dart:math' as math;
import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// A lit "connection point" on the globe — a server location, or the
/// user's own approximate location. Purely decorative for now; wire this
/// up to real server coordinates once the VPN engine is in.
class GlobePoint {
  const GlobePoint({required this.lat, required this.lon, this.label});

  /// Degrees, -90..90.
  final double lat;

  /// Degrees, -180..180.
  final double lon;
  final String? label;
}

/// A slowly, continuously rotating wireframe globe with a glossy lit-sphere
/// shading underneath — no bitmap assets, so it renders identically on
/// every platform and never needs a texture to be shipped/updated.
///
/// The rotation is deliberately slow (one full turn every [revolutionTime])
/// and the wireframe is faint — "calm and dreamy" was the brief, not a
/// spinning-logo intro.
class RotatingGlobe extends StatefulWidget {
  const RotatingGlobe({
    super.key,
    this.size = 260,
    this.revolutionTime = const Duration(seconds: 50),
    this.points = const [],
  });

  final double size;
  final Duration revolutionTime;
  final List<GlobePoint> points;

  @override
  State<RotatingGlobe> createState() => _RotatingGlobeState();
}

class _RotatingGlobeState extends State<RotatingGlobe>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(vsync: this, duration: widget.revolutionTime)
      ..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: widget.size,
      height: widget.size,
      child: AnimatedBuilder(
        animation: _controller,
        builder: (context, _) {
          return CustomPaint(
            painter: _GlobePainter(
              rotation: _controller.value * 2 * math.pi,
              points: widget.points,
            ),
          );
        },
      ),
    );
  }
}

class _GlobePainter extends CustomPainter {
  _GlobePainter({required this.rotation, required this.points});

  final double rotation;
  final List<GlobePoint> points;

  static const _latLines = 5; // parallels above/below the equator, per hemisphere step
  static const _lonLines = 8; // meridians around the sphere

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final radius = math.min(size.width, size.height) / 2;

    _paintGlowRings(canvas, center, radius);
    _paintSphere(canvas, center, radius);
    _paintWireframe(canvas, center, radius);
    _paintPoints(canvas, center, radius);
  }

  void _paintGlowRings(Canvas canvas, Offset center, double radius) {
    for (final factor in [1.55, 1.32, 1.14]) {
      final paint = Paint()
        ..color = AppColors.accent.withOpacity(0.05)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1;
      canvas.drawCircle(center, radius * factor, paint);
    }
  }

  void _paintSphere(Canvas canvas, Offset center, double radius) {
    final lightOffset = Offset(-radius * 0.35, -radius * 0.4);
    const gradient = RadialGradient(
      center: Alignment(-0.35, -0.4),
      radius: 0.95,
      colors: [
        AppColors.globeRim,
        AppColors.globeCore,
        AppColors.globeShadow,
      ],
      stops: [0.0, 0.55, 1.0],
    );
    final rect = Rect.fromCircle(center: center, radius: radius);
    final paint = Paint()..shader = gradient.createShader(rect);
    canvas.drawCircle(center, radius, paint);

    // A soft highlight blob, offset toward the light, for the "glossy"
    // look rather than a flat-shaded circle.
    final highlight = Paint()
      ..color = Colors.white.withOpacity(0.10)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 18);
    canvas.drawCircle(center + lightOffset * 0.6, radius * 0.35, highlight);
  }

  /// Orthographic projection of a (lat, lon) sphere point onto the 2D
  /// circle, given the current rotation. Returns null when the point is on
  /// the far side (so callers can skip drawing it, or fade it out).
  ({Offset offset, double depth})? _project(
    double latDeg, double lonDeg, Offset center, double radius,
  ) {
    final lat = latDeg * math.pi / 180;
    final lon = lonDeg * math.pi / 180 + rotation;
    final cosLat = math.cos(lat);
    final x = radius * cosLat * math.sin(lon);
    final y = -radius * math.sin(lat);
    final z = cosLat * math.cos(lon); // -1..1, front-facing when > 0
    return (offset: center + Offset(x, y), depth: z);
  }

  void _paintWireframe(Canvas canvas, Offset center, double radius) {
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.8
      ..color = AppColors.accentSoft.withOpacity(0.16);

    canvas.save();
    canvas.clipPath(Path()..addOval(Rect.fromCircle(center: center, radius: radius)));

    // Parallels (latitude rings), skipping the poles where they'd be a dot.
    for (var i = -_latLines; i <= _latLines; i++) {
      final lat = i * (80 / _latLines);
      _drawSmallCircle(canvas, center, radius, lat, paint);
    }

    // Meridians (longitude rings), each a great circle through both poles.
    for (var i = 0; i < _lonLines; i++) {
      final lon = i * (180 / _lonLines);
      _drawMeridian(canvas, center, radius, lon, paint);
    }

    canvas.restore();
  }

  void _drawSmallCircle(
    Canvas canvas, Offset center, double radius, double latDeg, Paint paint,
  ) {
    final path = Path();
    var started = false;
    for (var lonDeg = 0; lonDeg <= 360; lonDeg += 4) {
      final p = _project(latDeg, lonDeg.toDouble(), center, radius);
      if (p == null || p.depth < 0) {
        started = false;
        continue;
      }
      if (!started) {
        path.moveTo(p.offset.dx, p.offset.dy);
        started = true;
      } else {
        path.lineTo(p.offset.dx, p.offset.dy);
      }
    }
    canvas.drawPath(path, paint);
  }

  void _drawMeridian(
    Canvas canvas, Offset center, double radius, double lonDeg, Paint paint,
  ) {
    final path = Path();
    var started = false;
    for (var latDeg = -90; latDeg <= 90; latDeg += 4) {
      final p = _project(latDeg.toDouble(), lonDeg, center, radius);
      if (p == null || p.depth < 0) {
        started = false;
        continue;
      }
      if (!started) {
        path.moveTo(p.offset.dx, p.offset.dy);
        started = true;
      } else {
        path.lineTo(p.offset.dx, p.offset.dy);
      }
    }
    canvas.drawPath(path, paint);
  }

  void _paintPoints(Canvas canvas, Offset center, double radius) {
    for (final point in points) {
      final p = _project(point.lat, point.lon, center, radius);
      if (p == null || p.depth < 0.05) continue;
      final alpha = (0.4 + p.depth * 0.6).clamp(0.0, 1.0);
      final dotPaint = Paint()..color = AppColors.success.withOpacity(alpha);
      final glowPaint = Paint()
        ..color = AppColors.success.withOpacity(alpha * 0.35)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 6);
      canvas.drawCircle(p.offset, 6, glowPaint);
      canvas.drawCircle(p.offset, 2.6, dotPaint);
    }
  }

  @override
  bool shouldRepaint(covariant _GlobePainter oldDelegate) =>
      oldDelegate.rotation != rotation || oldDelegate.points != points;
}
