import 'package:flutter/material.dart';

import '../services/vpn_controller.dart';
import '../theme/app_theme.dart';
import '../widgets/connect_button.dart';
import '../widgets/flying_planes.dart';
import '../widgets/rotating_globe.dart';
import '../widgets/stat_tile.dart';
import '../widgets/traffic_graph.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.vpn});

  final VpnController vpn;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  @override
  void initState() {
    super.initState();
    widget.vpn.addListener(_onVpnChanged);
  }

  @override
  void dispose() {
    widget.vpn.removeListener(_onVpnChanged);
    super.dispose();
  }

  void _onVpnChanged() {
    if (widget.vpn.lastError != null) {
      final error = widget.vpn.lastError!;
      widget.vpn.lastError = null;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error)));
      });
    }
    setState(() {});
  }

  Future<void> _toggleConnection() async {
    if (widget.vpn.connecting) return;
    if (widget.vpn.connected) {
      await widget.vpn.disconnect();
    } else {
      await widget.vpn.connect();
    }
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
            child: TrafficGraph(samples: widget.vpn.samples),
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
                  connected: widget.vpn.connected,
                  connecting: widget.vpn.connecting,
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
    final label = widget.vpn.hasConfig
        ? (widget.vpn.configRemark ?? widget.vpn.configUrl!)
        : 'کانفیگی انتخاب نشده — از تب Configs اضافه کن';
    return Column(
      children: [
        const Text('Current Location', style: TextStyle(color: AppColors.textFaint, fontSize: 12)),
        const SizedBox(height: 2),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Text(
            label,
            textAlign: TextAlign.center,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: AppColors.textPrimary, fontSize: 15, fontWeight: FontWeight.w600),
          ),
        ),
      ],
    );
  }

  Widget _buildStatsRow() {
    final status = widget.vpn.status;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Expanded(child: StatTile(label: 'Download Speed', value: _fmtSpeed(status.downloadSpeed.toDouble()))),
          Expanded(child: StatTile(label: 'Upload Speed', value: _fmtSpeed(status.uploadSpeed.toDouble()))),
          Expanded(child: StatTile(label: 'Duration', value: widget.vpn.connected ? status.duration : '--')),
        ],
      ),
    );
  }
}
