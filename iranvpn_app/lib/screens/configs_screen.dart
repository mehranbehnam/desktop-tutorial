import 'package:flutter/material.dart';

import '../services/vpn_controller.dart';
import '../theme/app_theme.dart';

/// Paste-a-link config entry — the minimum needed to actually test a
/// connection end-to-end. A real list (multiple saved servers, ping-sort,
/// subscription import/update) is the next pass; for now this holds one
/// config at a time, matching what VpnController persists.
class ConfigsScreen extends StatefulWidget {
  const ConfigsScreen({super.key, required this.vpn});

  final VpnController vpn;

  @override
  State<ConfigsScreen> createState() => _ConfigsScreenState();
}

class _ConfigsScreenState extends State<ConfigsScreen> {
  final _controller = TextEditingController();
  String? _error;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    widget.vpn.addListener(_onVpnChanged);
  }

  @override
  void dispose() {
    widget.vpn.removeListener(_onVpnChanged);
    _controller.dispose();
    super.dispose();
  }

  void _onVpnChanged() => setState(() {});

  Future<void> _save() async {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.vpn.setConfigFromUrl(text);
      _controller.clear();
    } catch (e) {
      setState(() => _error = 'لینک نامعتبره: $e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _remove() async {
    await widget.vpn.clearConfig();
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 20, 20, 20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'کانفیگ‌ها',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.textPrimary),
            ),
            const SizedBox(height: 4),
            const Text(
              'لینک vless:// یا vmess:// یا trojan:// رو اینجا بچسبون.',
              style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
            ),
            const SizedBox(height: 20),
            if (widget.vpn.hasConfig) _buildCurrentConfig() else _buildEmptyState(),
            const SizedBox(height: 20),
            _buildInputField(),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(_error!, style: const TextStyle(color: Colors.redAccent, fontSize: 13)),
            ],
            const SizedBox(height: 12),
            ElevatedButton(
              onPressed: _saving ? null : _save,
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.accent,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
              child: Text(_saving ? 'در حال بررسی…' : 'ذخیره و استفاده از این کانفیگ'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border),
      ),
      child: const Text(
        'هنوز کانفیگی اضافه نشده.',
        style: TextStyle(color: AppColors.textSecondary),
      ),
    );
  }

  Widget _buildCurrentConfig() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: widget.vpn.connected ? AppColors.success.withOpacity(0.2) : AppColors.accent.withOpacity(0.15),
              shape: BoxShape.circle,
            ),
            child: Icon(
              widget.vpn.connected ? Icons.check_circle : Icons.dns_outlined,
              color: widget.vpn.connected ? AppColors.success : AppColors.accent,
              size: 20,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.vpn.configRemark ?? '',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: AppColors.textPrimary, fontWeight: FontWeight.w600),
                ),
                Text(
                  widget.vpn.connected ? 'متصل' : 'قطع',
                  style: TextStyle(
                    color: widget.vpn.connected ? AppColors.success : AppColors.textFaint,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
          IconButton(
            onPressed: _remove,
            icon: const Icon(Icons.delete_outline, color: AppColors.textSecondary),
          ),
        ],
      ),
    );
  }

  Widget _buildInputField() {
    return TextField(
      controller: _controller,
      minLines: 2,
      maxLines: 4,
      style: const TextStyle(color: AppColors.textPrimary),
      decoration: InputDecoration(
        hintText: 'vless://...',
        hintStyle: const TextStyle(color: AppColors.textFaint),
        filled: true,
        fillColor: AppColors.surface,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: AppColors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: AppColors.border),
        ),
      ),
    );
  }
}
