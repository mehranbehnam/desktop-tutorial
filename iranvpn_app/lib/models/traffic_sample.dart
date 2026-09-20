/// One tick of throughput. Bytes/sec, so the UI layer decides how to
/// format (KB/s, MB/s, ...).
class TrafficSample {
  const TrafficSample({required this.download, required this.upload, required this.at});

  final double download;
  final double upload;
  final DateTime at;
}
