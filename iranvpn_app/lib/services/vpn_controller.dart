import 'package:flutter/foundation.dart';
import 'package:flutter_v2ray/flutter_v2ray.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/traffic_sample.dart';

const _prefKeyConfigUrl = 'iranvpn.config_url';
const _prefKeyConfigRemark = 'iranvpn.config_remark';

/// Wraps flutter_v2ray (Xray core) so the home screen's connect button,
/// graph and stat tiles drive an actual VPN tunnel.
///
/// One config at a time for now (whatever was last saved from the Configs
/// screen) — a real multi-server list is the next milestone once this
/// end-to-end path is confirmed working on a device.
class VpnController extends ChangeNotifier {
  VpnController() {
    _v2ray = FlutterV2ray(onStatusChanged: _onStatusChanged);
  }

  late final FlutterV2ray _v2ray;

  String? configUrl;
  String? configRemark;
  V2RayStatus status = V2RayStatus();
  String? lastError;

  final List<TrafficSample> _samples = [];
  static const _maxSamples = 60;

  List<TrafficSample> get samples => List.unmodifiable(_samples);
  bool get hasConfig => configUrl != null;
  bool get connected => status.state == 'CONNECTED';
  bool get connecting => status.state == 'CONNECTING';

  Future<void> init() async {
    await _v2ray.initializeV2Ray();
    final prefs = await SharedPreferences.getInstance();
    configUrl = prefs.getString(_prefKeyConfigUrl);
    configRemark = prefs.getString(_prefKeyConfigRemark);
    notifyListeners();
  }

  /// Parses+saves a vless/vmess/trojan/ss/socks share link from the
  /// Configs screen. Throws ArgumentError (via parseFromURL) if the link
  /// isn't a recognized format — caller shows that to the user.
  Future<void> setConfigFromUrl(String rawUrl) async {
    final parsed = FlutterV2ray.parseFromURL(rawUrl.trim());
    configUrl = rawUrl.trim();
    configRemark = parsed.remark.isEmpty ? parsed.address : parsed.remark;

    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefKeyConfigUrl, configUrl!);
    await prefs.setString(_prefKeyConfigRemark, configRemark!);
    notifyListeners();
  }

  Future<void> clearConfig() async {
    if (connected || connecting) {
      await disconnect();
    }
    configUrl = null;
    configRemark = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_prefKeyConfigUrl);
    await prefs.remove(_prefKeyConfigRemark);
    notifyListeners();
  }

  Future<void> connect() async {
    if (configUrl == null) {
      lastError = 'اول یه کانفیگ از تب Configs اضافه کن.';
      notifyListeners();
      return;
    }
    lastError = null;
    try {
      final granted = await _v2ray.requestPermission();
      if (!granted) {
        lastError = 'اجازه‌ی VPN داده نشد.';
        notifyListeners();
        return;
      }
      final parsed = FlutterV2ray.parseFromURL(configUrl!);
      await _v2ray.startV2Ray(
        remark: configRemark ?? parsed.remark,
        config: parsed.getFullConfiguration(),
      );
    } catch (e) {
      lastError = '$e';
      notifyListeners();
    }
  }

  Future<void> disconnect() async {
    await _v2ray.stopV2Ray();
  }

  void _onStatusChanged(V2RayStatus newStatus) {
    status = newStatus;
    if (newStatus.state == 'CONNECTED') {
      _samples.add(TrafficSample(
        download: newStatus.downloadSpeed.toDouble(),
        upload: newStatus.uploadSpeed.toDouble(),
        at: DateTime.now(),
      ));
      if (_samples.length > _maxSamples) {
        _samples.removeAt(0);
      }
    } else if (_samples.isNotEmpty) {
      _samples.clear();
    }
    notifyListeners();
  }
}
