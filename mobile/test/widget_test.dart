import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:quranify/main.dart';
import 'package:quranify/state/app_state.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('unauthenticated user sees the login screen', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final state = AppState();
    await tester.pumpWidget(
      ChangeNotifierProvider.value(value: state, child: const QuranifyApp()),
    );
    await state.load();
    await tester.pumpAndSettle();
    expect(find.text('Quranify'), findsOneWidget);
    expect(find.text('Sign In'), findsOneWidget);
    expect(find.byType(TextField), findsNWidgets(2));
  });
}
