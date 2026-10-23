import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:quranify/screens/auth_screens.dart';
import 'package:quranify/services/api_client.dart';
import 'package:quranify/state/app_state.dart';
import 'package:shared_preferences/shared_preferences.dart';

class StalledBodyClient extends http.BaseClient {
  bool aborted = false;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final body = StreamController<List<int>>();
    if (request is http.Abortable) {
      request.abortTrigger?.then((_) {
        aborted = true;
        body.addError(http.RequestAbortedException(request.url));
        body.close();
      });
    }
    return http.StreamedResponse(body.stream, 201);
  }
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));
  testWidgets('unreachable registration stops Creating and enables retry',
      (tester) async {
    final client = MockClient((_) => Completer<http.Response>().future);
    final state = AppState(
        api: ApiClient(
            baseUrl: 'http://unreachable.test',
            client: client,
            requestTimeout: const Duration(milliseconds: 50)));
    await tester.pumpWidget(ChangeNotifierProvider.value(
        value: state, child: const MaterialApp(home: RegisterScreen())));
    await tester.enterText(find.byType(TextField).at(0), 'Connection test');
    await tester.enterText(
        find.byType(TextField).at(1), 'probe@example.invalid');
    await tester.enterText(find.byType(TextField).at(2), 'test-password');
    await tester.tap(find.text('Create Account'));
    await tester.pump();
    expect(find.text('Creating…'), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump();
    expect(find.text('Creating…'), findsNothing);
    expect(find.textContaining('timed out'), findsOneWidget);
    expect(
        tester
            .widget<FilledButton>(
                find.widgetWithText(FilledButton, 'Create Account'))
            .onPressed,
        isNotNull);
    await tester.pumpWidget(const SizedBox());
    client.close();
  });

  test('registration timeout includes a stalled response body and aborts it',
      () async {
    final client = StalledBodyClient();
    final api = ApiClient(
        baseUrl: 'http://unreachable.test',
        client: client,
        requestTimeout: const Duration(milliseconds: 20));
    await expectLater(
        api.register('probe@example.invalid', 'test-password'),
        throwsA(isA<ApiException>()
            .having((e) => e.message, 'message', contains('timed out'))));
    await Future<void>.delayed(Duration.zero);
    expect(client.aborted, isTrue);
  });

  test('successful registration still saves the user and token', () async {
    final client = MockClient((request) async => http.Response(
        jsonEncode({
          'token': 'test-token',
          'user': {
            'id': 1,
            'email': 'probe@example.invalid',
            'name': 'Probe',
            'mode': 'normal'
          },
        }),
        201));
    final state = AppState(
        api: ApiClient(baseUrl: 'http://reachable.test', client: client));
    await state.register('probe@example.invalid', 'test-password');
    expect(state.isLoggedIn, isTrue);
    expect((await SharedPreferences.getInstance()).getString('token'),
        'test-token');
    client.close();
  });

  testWidgets(
      'server address can be tested and changed before creating an account',
      (tester) async {
    final client = MockClient((request) async {
      expect(request.url.toString(), 'http://reachable.test:8000/health');
      return http.Response('{"status":"ok","service":"quranify-api"}', 200);
    });
    final state =
        AppState(api: ApiClient(baseUrl: 'http://old.test', client: client));
    await tester.pumpWidget(ChangeNotifierProvider.value(
        value: state, child: const MaterialApp(home: RegisterScreen())));
    await tester.tap(find.text('Server connection'));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byType(TextField).last, 'http://reachable.test:8000/');
    await tester.tap(find.text('Test and save'));
    await tester.pumpAndSettle();
    expect(state.api.baseUrl, 'http://reachable.test:8000');
    expect((await SharedPreferences.getInstance()).getString('api_url'),
        state.api.baseUrl);
    expect(find.text('Create Account'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    client.close();
  });
}
