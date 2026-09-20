import 'dart:math' as math;
import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// A handful of tiny paper-plane icons drifting along slow elliptical
/// arcs around the globe — "very minimal, calm, dreamy" per the brief, so
/// each plane takes a full minute or more to cross the screen and fades
/// in/out at the ends of its arc instead of popping in and out.
class FlyingPlanes extends StatefulWidget {
  const FlyingPlanes({super.key, required this.areaSize, this.count = 3});

  final Size areaSize;
  final int count;

  @override
  State<FlyingPlanes> createState() => _FlyingPlanesState();
}

class _FlyingPlanesState extends State<FlyingPlanes>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final List<_PlanePath> _paths;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(vsync: this, duration: const Duration(seconds: 60))
      ..repeat();
    _paths = List.generate(widget.count, (i) => _PlanePath.forIndex(i, widget.count));
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox.fromSize(
      size: widget.areaSize,
      child: AnimatedBuilder(
        animation: _controller,
        builder: (context, _) {
          return Stack(
            children: [
              for (final path in _paths)
                _buildPlane(path, _controller.value),
            ],
          );
        },
      ),
    );
  }

  Widget _buildPlane(_PlanePath path, double globalT) {
    final t = (globalT + path.phase) % 1.0;
    final center = widget.areaSize.center(Offset.zero);
    final rx = widget.areaSize.width * path.radiusFactorX;
    final ry = widget.areaSize.height * path.radiusFactorY;
    final angle = t * 2 * math.pi;
    final dx = center.dx + rx * math.cos(angle);
    final dy = center.dy + ry * math.sin(angle) * path.tilt;

    // Fade in/out near the "back" of the arc so a plane never just
    // pops into existence — it drifts up out of the haze instead.
    final depth = math.sin(angle) * path.tilt;
    final opacity = (0.15 + (depth + 1) / 2 * 0.55).clamp(0.0, 0.7);

    final heading = angle + math.pi / 2; // tangent direction of travel

    return Positioned(
      left: dx - 10,
      top: dy - 10,
      child: Opacity(
        opacity: opacity,
        child: Transform.rotate(
          angle: heading,
          child: Icon(Icons.send_rounded, size: 14, color: AppColors.textPrimary),
        ),
      ),
    );
  }
}

class _PlanePath {
  const _PlanePath({
    required this.phase,
    required this.radiusFactorX,
    required this.radiusFactorY,
    required this.tilt,
  });

  factory _PlanePath.forIndex(int i, int count) {
    return _PlanePath(
      phase: i / count,
      radiusFactorX: 0.62 + (i % 2) * 0.08,
      radiusFactorY: 0.30 + (i % 3) * 0.05,
      tilt: i.isEven ? 1 : -1,
    );
  }

  final double phase;
  final double radiusFactorX;
  final double radiusFactorY;
  final double tilt;
}
