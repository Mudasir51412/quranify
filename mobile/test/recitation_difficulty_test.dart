import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:quranify/models/models.dart';
import 'package:quranify/screens/profile_screen.dart';
import 'package:quranify/state/app_state.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('Profile Settings offers and persists recitation difficulty',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final state = AppState();
    await state.load();
    state.setUser(const UserProfile(
      id: 1,
      email: 'reciter@example.test',
      name: 'Reciter',
      mode: 'normal',
      notificationsEnabled: false,
    ));
    await tester.pumpWidget(ChangeNotifierProvider.value(
      value: state,
      child: const MaterialApp(home: ProfileScreen()),
    ));
    final preference = find.byKey(const Key('recitation-difficulty'));
    await tester.ensureVisible(preference);
    expect(find.text('Settings'), findsOneWidget);
    expect(
        tester.widget<DropdownButton<RecitationDifficulty>>(preference).value,
        RecitationDifficulty.expert);
    await tester.tap(preference);
    await tester.pumpAndSettle();
    expect(find.text('Beginner'), findsOneWidget);
    expect(find.text('Intermediate'), findsOneWidget);
    await tester.tap(find.text('Intermediate'));
    await tester.pumpAndSettle();
    expect(state.recitationDifficulty, RecitationDifficulty.intermediate);
    expect(state.user!.mode, 'normal');
    expect(
        (await SharedPreferences.getInstance())
            .getString('recitation_difficulty'),
        'intermediate');
    final reloaded = AppState();
    await reloaded.load();
    expect(reloaded.recitationDifficulty, RecitationDifficulty.intermediate);
  });

  test('invalid saved recitation difficulty falls back to Expert', () async {
    SharedPreferences.setMockInitialValues({'recitation_difficulty': 123});
    final state = AppState();
    await state.load();
    expect(state.recitationDifficulty, RecitationDifficulty.expert);
  });
}
