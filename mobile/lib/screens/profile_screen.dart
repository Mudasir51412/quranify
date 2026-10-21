import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../state/app_state.dart';
import '../widgets/common.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  late TextEditingController _apiUrl;
  late TextEditingController _name;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final state = context.read<AppState>();
    _apiUrl = TextEditingController(text: state.api.baseUrl);
    _name = TextEditingController(text: state.user?.name ?? '');
  }

  @override
  void dispose() {
    _apiUrl.dispose();
    _name.dispose();
    super.dispose();
  }

  Future<void> _patch(Map<String, dynamic> patch) async {
    final state = context.read<AppState>();
    setState(() => _saving = true);
    try {
      state.setUser(await state.api.patchMe(patch));
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.message)));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final user = state.user;
    if (user == null) {
      return const Scaffold(body: Center(child: Text('Not signed in')));
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Profile')),
      body: ListView(
        children: [
          const SizedBox(height: 16),
          Center(
            child: Column(
              children: [
                const CircleAvatar(radius: 36, child: Icon(Icons.person, size: 36)),
                const SizedBox(height: 8),
                Text(user.name.isEmpty ? 'Quranify User' : user.name,
                    style: Theme.of(context).textTheme.titleLarge),
                Text(user.email, style: const TextStyle(color: Colors.grey)),
              ],
            ),
          ),
          SectionCard(
            title: 'Settings',
            child: Column(
              children: [
                TextField(
                  controller: _name,
                  decoration: const InputDecoration(labelText: 'Name'),
                  onSubmitted: (v) => _patch({'name': v.trim()}),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    const Expanded(child: Text('Learning mode')),
                    SegmentedButton<String>(
                      segments: const [
                        ButtonSegment(value: 'normal', label: Text('Normal')),
                        ButtonSegment(value: 'hafiz', label: Text('Hafiz')),
                      ],
                      selected: {user.mode},
                      onSelectionChanged:
                          _saving ? null : (s) => _patch({'mode': s.first}),
                    ),
                  ],
                ),
                SwitchListTile(
                  title: const Text('Daily reminder notifications'),
                  subtitle: const Text('Ayah & Hadith of the day reminder'),
                  value: user.notificationsEnabled,
                  onChanged: _saving
                      ? null
                      : (v) => _patch({'notifications_enabled': v}),
                ),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.bookmark),
                  title: const Text('Reading position'),
                  subtitle: Text(user.lastSurah == null
                      ? 'Not set yet — save one from any Surah page'
                      : 'Surah ${user.lastSurah}, Ayah ${user.lastAyah}'),
                ),
              ],
            ),
          ),
          SectionCard(
            title: 'Connection',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                  controller: _apiUrl,
                  decoration: const InputDecoration(
                    labelText: 'API URL',
                    helperText:
                        'Emulator: http://10.0.2.2:8000 · Phone on same Wi-Fi: your PC\'s LAN IP',
                  ),
                ),
                const SizedBox(height: 8),
                FilledButton.tonal(
                  onPressed: () async {
                    final messenger = ScaffoldMessenger.of(context);
                    await state.setApiUrl(_apiUrl.text);
                    await state.refreshUser();
                    messenger.showSnackBar(
                        const SnackBar(content: Text('API URL saved')));
                  },
                  child: const Text('Save API URL'),
                ),
              ],
            ),
          ),
          const SectionCard(
            title: 'Offline availability',
            child: Text(
              'Quran text you open is saved on this device and stays readable '
              'without internet. Your reading position and profile are stored '
              'locally too. Recitation analysis needs a connection to the '
              'server in this version — an on-device model is planned.',
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: OutlinedButton.icon(
              icon: const Icon(Icons.logout),
              label: const Text('Sign Out'),
              onPressed: () => state.logout(),
            ),
          ),
        ],
      ),
    );
  }
}
