import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Animated, FlatList, SafeAreaView, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';

// Use your ngrok host (no scheme), e.g. 'abcd-1-2-3-4.ngrok-free.app'
// For a local emulator without ngrok: Android emulator '10.0.2.2:3000', iOS simulator 'localhost:3000'
const HOST = '192.168.1.9:3000'; // <-- CHANGE THIS
const SECURE = !/^(localhost|10\.0\.2\.2|\d+\.\d+\.\d+\.\d+)/.test(HOST);
const WS_URL = `${SECURE ? 'wss' : 'ws'}://${HOST}/ws`;

function useLiveLeads() {
  const [leads, setLeads] = useState([]);
  const [connected, setConnected] = useState(false);
  const [freshIds, setFreshIds] = useState({});
  const retry = useRef(0);
  const ws = useRef(null);
  const timer = useRef(null);
  const closed = useRef(false);

  const connect = useCallback(() => {
    const sock = new WebSocket(WS_URL);
    ws.current = sock;

    sock.onopen = () => { retry.current = 0; setConnected(true); };
    sock.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'snapshot') {
        setLeads(msg.leads);
      } else if (msg.type === 'lead') {
        setLeads((prev) => (prev.some((l) => l.id === msg.lead.id) ? prev : [msg.lead, ...prev]));
        setFreshIds((f) => ({ ...f, [msg.lead.id]: true }));
        setTimeout(() => setFreshIds((f) => { const { [msg.lead.id]: _, ...rest } = f; return rest; }), 4000);
      }
    };
    sock.onclose = () => {
      setConnected(false);
      if (closed.current) return;
      // exponential backoff reconnect, max 10s; server re-sends a snapshot on reconnect
      const delay = Math.min(1000 * 2 ** retry.current++, 10000);
      timer.current = setTimeout(connect, delay);
    };
    sock.onerror = () => sock.close();
  }, []);

  useEffect(() => {
    connect();
    return () => { closed.current = true; clearTimeout(timer.current); ws.current && ws.current.close(); };
  }, [connect]);

  return { leads, connected, freshIds };
}

function LeadCard({ lead, fresh }) {
  const anim = useRef(new Animated.Value(fresh ? 0 : 1)).current;
  useEffect(() => {
    if (fresh) Animated.timing(anim, { toValue: 1, duration: 500, useNativeDriver: true }).start();
  }, [fresh, anim]);

  const f = lead.fields || {};
  const name = f.full_name || [f.first_name, f.last_name].filter(Boolean).join(' ') || 'Unknown';
  const extra = Object.entries(f).filter(([k]) => !['full_name', 'first_name', 'last_name'].includes(k));

  return (
    <Animated.View style={[styles.card, fresh && styles.cardFresh, { opacity: anim, transform: [{ translateY: anim.interpolate({ inputRange: [0, 1], outputRange: [-12, 0] }) }] }]}>
      <View style={styles.row}>
        <Text style={styles.name}>{name}</Text>
        {fresh && <Text style={styles.badge}>NEW</Text>}
      </View>
      {extra.map(([k, v]) => (
        <Text key={k} style={styles.field}><Text style={styles.key}>{k}: </Text>{v}</Text>
      ))}
      {lead.status === 'fetch_failed' && <Text style={styles.warn}>Lead received but details could not be fetched (check PAGE_ACCESS_TOKEN)</Text>}
      <Text style={styles.meta}>#{lead.id} · {new Date(lead.receivedAt).toLocaleTimeString()}</Text>
    </Animated.View>
  );
}

export default function App() {
  const { leads, connected, freshIds } = useLiveLeads();
  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="dark" />
      <View style={styles.header}>
        <Text style={styles.title}>Live Leads ({leads.length})</Text>
        <View style={styles.status}>
          <View style={[styles.dot, { backgroundColor: connected ? '#22c55e' : '#ef4444' }]} />
          <Text>{connected ? 'Live' : 'Reconnecting…'}</Text>
        </View>
      </View>
      <FlatList
        data={leads}
        keyExtractor={(l) => l.id}
        renderItem={({ item }) => <LeadCard lead={item} fresh={!!freshIds[item.id]} />}
        contentContainerStyle={{ padding: 16 }}
        ListEmptyComponent={<Text style={styles.empty}>Waiting for leads… submit one from Meta's Lead Ads Testing Tool.</Text>}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#f4f5f7' },
  header: { padding: 16, paddingTop: 40, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  title: { fontSize: 22, fontWeight: '700' },
  status: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  card: { backgroundColor: '#fff', borderRadius: 12, padding: 14, marginBottom: 12, borderWidth: 1, borderColor: '#e5e7eb' },
  cardFresh: { borderColor: '#22c55e', backgroundColor: '#f0fdf4' },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  name: { fontSize: 17, fontWeight: '600' },
  badge: { backgroundColor: '#22c55e', color: '#fff', fontSize: 11, fontWeight: '700', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 8, overflow: 'hidden' },
  field: { marginTop: 4, color: '#111827' },
  key: { color: '#6b7280' },
  warn: { marginTop: 6, color: '#b45309' },
  meta: { marginTop: 8, fontSize: 12, color: '#9ca3af' },
  empty: { textAlign: 'center', marginTop: 60, color: '#6b7280' },
});
