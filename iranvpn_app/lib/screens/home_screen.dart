import 'package:flutter/material.dart';

import '../services/traffic_controller.dart';
import '../theme/app_theme.dart';
import '../widgets/connect_button.dart';
import '../widgets/flying_planes.dart';
import '../widgets/rotating_globe.dart';
import '../widgets/stat_tile.dart';
import '../widgets/traffic_graph.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late final TrafficController _traffic;
  bool _connecting = false;

  static const _serverLabel = 'ws-tls-cdn1-کلاینت';

  @override
  void initState() {
    super.initState();
    _traffic = TrafficController();
    _traffic.addListener(_onTrafficChanged);
  }

  @override
  void dispose() {
    _traffic.removeListener(_onTrafficChanged);
    _traffic.dispose();
    super.dispose();
  }

  void _onTrafficChanged() => setState(() {});

  Future<void> _toggleConnection() async {
    if (_connecting) return;
    if (_traffic.connected) {
      _traffic.setConnected(false);
      return;
    }
    setState(() => _connecting = true);
    // Placeholder handshake delay — replace with the real VPN engine's
    // connect() future once it's wired in.
    await Future.delayed(const Duration(milliseconds: 900));
    if (!mounted) return;
    setState(() => _connecting = false);
    _traffic.setConnected(true);
  }

  String _fmtSpeed(double bytesPerSec) {
    if (bytesPerSec < 1024) return '${bytesPerSec.toStringAsFixed(0)} B/s';
    if (bytesPerSec < 1024 * 1024) return '${(bytesPerSec / 1024).toStringAsFixed(0)} KB/s';
    return '${(bytesPerSec / 1024 / 1024).toStringAsFixed(1)} MB/s';
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Column(
        children: [
          _buildHeader(),
          Expanded(child: _buildGlobeArea()),
          _buildLocationLabel(),
          const SizedBox(height: 12),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: TrafficGraph(samples: _traffic.samples),
          ),
          const SizedBox(height: 12),
          _buildStatsRow(),
          const SizedBox(height: 12),
        ],
      ),
    );
  }

  Widget _buildHeader() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
      child: Row(
        children: [
          Container(
            width: 34,
            height: 34,
            decoration: const BoxDecoration(
              shape: BoxShape.circle,
              gradient: LinearGradient(colors: [AppColors.accent, AppColors.accentSoft]),
            ),
            child: const Icon(Icons.shield_moon_rounded, size: 18, color: Colors.white),
          ),
          const SizedBox(width: 10),
          const Expanded(
            child: Text(
              'IranVPN Connect',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: AppColors.textPrimary),
            ),
          ),
          IconButton(
            onPressed: () {},
            icon: const Icon(Icons.settings_outlined, color: AppColors.textSecondary),
          ),
        ],
      ),
    );
  }

  Widget _buildGlobeArea() {
    return LayoutBuilder(
      builder: (context, constraints) {
        final side = constraints.biggest.shortestSide;
        final globeSize = side * 0.6;
        const buttonSize = 96.0;
        const buttonGap = 22.0; // clear space between the button and the globe's rim
        final areaSize = Size(constraints.maxWidth, constraints.maxHeight);

        // Anchor the globe a little below center so there's room above it
        // for the connect button to float clear of the sphere, matching
        // the reference layout instead of badge-stamping the button onto
        // the globe's rim.
        final globeTop = (constraints.maxHeight - globeSize) / 2 + 26;
        final buttonTop = globeTop - buttonSize - buttonGap;

        return Stack(
          children: [
            FlyingPlanes(areaSize: areaSize),
            Positioned(
              top: globeTop,
              left: 0,
              right: 0,
              child: Center(
                child: RotatingGlobe(
                  size: globeSize,
                  points: const [
                    GlobePoint(lat: 35.7, lon: 51.4, label: 'Tehran'),
                    GlobePoint(lat: 52.5, lon: 13.4, label: 'Berlin'),
                    GlobePoint(lat: 1.35, lon: 103.8, label: 'Singapore'),
                  ],
                ),
              ),
            ),
            Positioned(
              top: buttonTop,
              left: 0,
              right: 0,
              child: Center(
                child: ConnectButton(
                  connected: _traffic.connected,
                  connecting: _connecting,
                  onTap: _toggleConnection,
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _buildLocationLabel() {
    return Column(
      children: [
        const Text('Current Location', style: TextStyle(color: AppColors.textFaint, fontSize: 12)),
        const SizedBox(height: 2),
        Text(
          _serverLabel,
          style: const TextStyle(color: AppColors.textPrimary, fontSize: 15, fontWeight: FontWeight.w600),
        ),
      ],
    );
  }

  Widget _buildStatsRow() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Expanded(child: StatTile(label: 'Download Speed', value: _fmtSpeed(_traffic.downloadBytesPerSec))),
          Expanded(child: StatTile(label: 'Upload Speed', value: _fmtSpeed(_traffic.uploadBytesPerSec))),
          Expanded(child: StatTile(label: 'Ping', value: _traffic.connected ? '${_traffic.pingMs} ms' : '--')),
        ],
      ),
    );
  }
}
