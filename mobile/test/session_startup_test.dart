import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:quranify/models/models.dart';
import 'package:quranify/services/api_client.dart';
import 'package:quranify/state/app_state.dart';

class StartupApi extends ApiClient {
  StartupApi() : super(baseUrl: 'http://unused');
  ApiException? failure;
  @override
  Future<UserProfile> me() async {
    if (failure != null) throw failure!;
    return const UserProfile(
        id: 1,
        email: 'test@example.invalid',
        name: '',
        mode: 'normal',
        notificationsEnabled: false);
  }
}

void main() {
  test('a temporary startup failure preserves the session for a later retry',
      () async {
    SharedPreferences.setMockInitialValues({'token': 'saved-session'});
    final api = StartupApi()..failure = ApiException('Cannot reach the server');
    final state = AppState(api: api);
    await state.load();
    expect((await SharedPreferences.getInstance()).getString('token'),
        'saved-session');
    expect(api.token, 'saved-session');
    api.failure = null;
    await state.load();
    expect(state.isLoggedIn, isTrue);
  });

  test('an explicitly rejected session is still discarded', () async {
    SharedPreferences.setMockInitialValues({'token': 'expired-session'});
    final api = StartupApi()..failure = ApiException('Invalid token', 401);
    await AppState(api: api).load();
    expect(api.token, isNull);
    expect((await SharedPreferences.getInstance()).getString('token'), isNull);
  });
}
