import { useCallback, useEffect, useRef, useState } from "react";
import {
  AppState,
  FlatList,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View,
  type ViewToken,
} from "react-native";

import {
  COPY,
  SHOWN_THRESHOLD,
  renderModel,
  sourceLine,
  type Card,
  type ShownCard,
} from "@techtrend/core";
import { createClient } from "@techtrend/api-client";

import { API_URL, feedback } from "@/queue";

/**
 * The dashboard. Same six screens, same events, same shared rules as web --
 * only the affordances differ (swipe vs keyboard, in-app browser vs <a>).
 */
export default function Dashboard() {
  const [cards, setCards] = useState<Card[]>([]);
  const [more, setMore] = useState<Card[]>([]);
  const shown = useRef<Map<number, ShownCard>>(new Map());

  useEffect(() => {
    createClient({ baseUrl: API_URL })
      .dashboard()
      .then((d) => {
        setCards(d.cards);
        setMore(d.more);
      })
      .catch(() => setCards([]));
  }, []);

  // Same predicate web feeds via IntersectionObserver -- imported, not
  // reimplemented.
  const onViewableItemsChanged = useRef(({ viewableItems }: { viewableItems: ViewToken[] }) => {
    for (const v of viewableItems) {
      const card = v.item as Card;
      if (v.isViewable && typeof v.index === "number") {
        shown.current.set(card.storyId, { storyId: card.storyId, position: v.index });
      }
    }
  }).current;

  const viewabilityConfig = useRef({
    itemVisiblePercentThreshold: SHOWN_THRESHOLD.ratio * 100,
    minimumViewTime: SHOWN_THRESHOLD.ms,
  }).current;

  // Backgrounding is mobile's equivalent of web's visibilitychange +
  // sendBeacon: the day's clean negatives must survive the app leaving.
  useEffect(() => {
    const sub = AppState.addEventListener("change", (state) => {
      if (state !== "active") {
        void feedback.dayComplete(Array.from(shown.current.values()));
      }
    });
    return () => sub.remove();
  }, []);

  const renderItem = useCallback(({ item, index }: { item: Card; index: number }) => {
    const m = renderModel(item);
    return (
      <View style={styles.card}>
        <Pressable
          onPress={() => {
            // Leaving the app for the publisher: the strongest positive signal.
            void feedback.track("tapped_through", item, index);
            void Linking.openURL(item.url);
          }}
        >
          <Text style={styles.headline}>{m.headline}</Text>
        </Pressable>

        <Text style={styles.meta}>
          {sourceLine(item.sourceName, item.sourceCount, item.publishedAt)}
          {m.labels.length > 0 ? `   ${m.labels.join(" · ")}` : ""}
        </Text>

        {/* null summary -> degrade to headline + source, never hide. */}
        {m.showSummary && <Text style={styles.summary}>{m.summary}</Text>}

        <Pressable onPress={() => void feedback.track("hidden", item, index)}>
          <Text style={styles.hide}>Hide</Text>
        </Pressable>
      </View>
    );
  }, []);

  return (
    <FlatList
      data={cards}
      keyExtractor={(c) => String(c.storyId)}
      renderItem={renderItem}
      onViewableItemsChanged={onViewableItemsChanged}
      viewabilityConfig={viewabilityConfig}
      contentContainerStyle={styles.list}
      // NO onEndReached. The bottom exists -- finishing is a feature, and the
      // API has no backfill path to call anyway (invariant #10).
      ListEmptyComponent={<Text style={styles.meta}>{COPY.quietDay}</Text>}
      ListFooterComponent={
        <View>
          <Text style={styles.dayEnd}>{COPY.dayEnd}</Text>
          {more.length > 0 && <Text style={styles.meta}>{COPY.moreBelow}</Text>}
        </View>
      }
    />
  );
}

const styles = StyleSheet.create({
  list: { padding: 16, paddingBottom: 64 },
  card: { borderBottomWidth: 1, borderBottomColor: "#e5e5e5", paddingVertical: 16 },
  headline: { fontSize: 17, fontWeight: "600", marginBottom: 6 },
  meta: { fontSize: 13, color: "#666", marginBottom: 8 },
  summary: { fontSize: 15, color: "#333", lineHeight: 22 },
  hide: { fontSize: 13, color: "#888", marginTop: 10 },
  dayEnd: {
    textAlign: "center", color: "#666", marginTop: 32, paddingTop: 24,
    borderTopWidth: 1, borderTopColor: "#e5e5e5",
  },
});
