import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../state/app_state.dart';

/// Connection recovery is available before signing in as well as in Profile.
class ServerConnectionButton extends StatelessWidget {
  const ServerConnectionButton({super.key});

  @override
  Widget build(BuildContext context) => TextButton.icon(
        icon: const Icon(Icons.settings_ethernet),
        label: const Text('Server connection'),
        onPressed: () async {
          final saved = await showDialog<bool>(
              context: context,
              builder: (_) =>
                  _ConnectionDialog(state: context.read<AppState>()));
          if (saved == true && context.mounted) {
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                content: Text('Server connection saved. You can retry now.')));
          }
        },
      );
}

class _ConnectionDialog extends StatefulWidget {
  final AppState state;
  const _ConnectionDialog({required this.state});

  @override
  State<_ConnectionDialog> createState() => _ConnectionDialogState();
}

class _ConnectionDialogState extends State<_ConnectionDialog> {
  late final _address = TextEditingController(text: widget.state.api.baseUrl);
  bool _busy = false;
  String? _error;

  Future<void> _save() async {
    final address = _address.text.trim().replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.tryParse(address);
    if (uri == null ||
        !['http', 'https'].contains(uri.scheme) ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment) {
      setState(
          () => _error = 'Enter a valid http:// or https:// server address.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.state.api.checkConnection(address);
      await widget.state.setApiUrl(address);
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) {
        setState(() =>
            _error = 'Could not save the server connection. Please try again.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _address.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Server connection'),
        content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                  'Use your PC’s current Wi-Fi address. The backend must be running.'),
              const SizedBox(height: 12),
              TextField(
                  controller: _address,
                  enabled: !_busy,
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  decoration: const InputDecoration(labelText: 'Server URL')),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: const TextStyle(color: Colors.red))
              ],
            ]),
        actions: [
          TextButton(
              onPressed: _busy ? null : () => Navigator.of(context).pop(),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: _busy ? null : _save,
              child: Text(_busy ? 'Checking…' : 'Test and save')),
        ],
      );
}
