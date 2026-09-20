import 'dart:async';
import 'dart:math';

import 'package:flutter/foundation.dart';

import '../models/traffic_sample.dart';

/// Feeds the live traffic graph and the Download/Upload/Ping stat tiles.
///
/// This is a UI-first pass: while there's no VPN engine wired in yet, it
/// generates a gentle random walk so the graph/tiles have something real
/// to animate. Swap [_generateMock] for a stream from the actual Xray
/// core (traffic stats API) once that's integrated — everything that
/// listens to this controller (the graph, the stat row) only depends on
/// [samples] and [pingMs], not on where the numbers come from.
class TrafficController extends ChangeNotifier {
  TrafficController({this.maxSamples = 60}) {
    _seed();
    _timer = Timer.periodic(const Duration(milliseconds: 800), (_) => _tick());
  }

  final int maxSamples;
  final _random = Random();
  final List<TrafficSample> _samples = [];
  Timer? _timer;
  double _download = 0;
  double _upload = 0;
  int _pingMs = 0;
  bool _connected = false;

  List<TrafficSample> get samples => List.unmodifiable(_samples);
  double get downloadBytesPerSec => _download;
  double get uploadBytesPerSec => _upload;
  int get pingMs => _pingMs;
  bool get connected => _connected;

  void setConnected(bool value) {
    _connected = value;
    if (!value) {
      _download = 0;
      _upload = 0;
      _pingMs = 0;
    }
    notifyListeners();
  }

  void _seed() {
    final now = DateTime.now();
    for (var i = maxSamples; i > 0; i--) {
      _samples.add(TrafficSample(
        download: 0,
        upload: 0,
        at: now.subtract(Duration(milliseconds: 800 * i)),
      ));
    }
  }

  void _tick() {
    if (_connected) {
      _download = (_download + (_random.nextDouble() - 0.45) * 60000)
          .clamp(0, 900000);
      _upload = (_upload + (_random.nextDouble() - 0.45) * 20000)
          .clamp(0, 300000);
      _pingMs = 30 + _random.nextInt(60);
    } else {
      _download = 0;
      _upload = 0;
      _pingMs = 0;
    }
    _samples.add(TrafficSample(download: _download, upload: _upload, at: DateTime.now()));
    if (_samples.length > maxSamples) {
      _samples.removeAt(0);
    }
    notifyListeners();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}
