import 'package:flutter/material.dart';

import '../models/traffic_sample.dart';
import '../theme/app_theme.dart';

/// A slim animated area chart of download throughput — the "Xray graph"
/// under the globe. Rebuilds on every new sample from
/// [TrafficController], so it stays live without its own timer.
class TrafficGraph extends StatelessWidget {
  const TrafficGraph({super.key, required this.samples, this.height = 56});

  final List<TrafficSample> samples;
  final double height;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: height,
      width: double.infinity,
      child: CustomPaint(
        painter: _GraphPainter(samples: samples),
      ),
    );
  }
}

class _GraphPainter extends CustomPainter {
  _GraphPainter({required this.samples});

  final List<TrafficSample> samples;

  @override
  void paint(Canvas canvas, Size size) {
    if (samples.length < 2) return;

    final maxValue = samples.map((s) => s.download).fold<double>(1, (a, b) => a > b ? a : b);
    final stepX = size.width / (samples.length - 1);

    final linePath = Path();
    final fillPath = Path();

    for (var i = 0; i < samples.length; i++) {
      final x = i * stepX;
      final normalized = maxValue == 0 ? 0.0 : samples[i].download / maxValue;
      final y = size.height - normalized * size.height * 0.92;
      if (i == 0) {
        linePath.moveTo(x, y);
        fillPath.moveTo(x, size.height);
        fillPath.lineTo(x, y);
      } else {
        linePath.lineTo(x, y);
        fillPath.lineTo(x, y);
      }
    }
    fillPath.lineTo(size.width, size.height);
    fillPath.close();

    final fillPaint = Paint()
      ..shader = const LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [AppColors.graphFillTop, AppColors.graphFillBottom],
      ).createShader(Rect.fromLTWH(0, 0, size.width, size.height));
    canvas.drawPath(fillPath, fillPaint);

    final linePaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6
      ..strokeJoin = StrokeJoin.round
      ..color = AppColors.graphLine;
    canvas.drawPath(linePath, linePaint);
  }

  @override
  bool shouldRepaint(covariant _GraphPainter oldDelegate) => true;
}
