import 'package:flutter_test/flutter_test.dart';

import 'package:iranvpn_app/main.dart';

void main() {
  testWidgets('home screen renders the connect button', (WidgetTester tester) async {
    await tester.pumpWidget(const IranVpnApp());
    await tester.pump();

    expect(find.text('IranVPN Connect'), findsOneWidget);
    expect(find.text('اتصال'), findsOneWidget);
  });
}
