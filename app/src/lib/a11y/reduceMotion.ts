import { useEffect, useState } from 'react';
import { AccessibilityInfo } from 'react-native';

/**
 * Whether this person has asked the system to stop moving things.
 *
 * Shared because two surfaces now animate: a tray developing while a panelist
 * speaks, and a card settling as somebody takes a seat. A second copy of this
 * is how one of them eventually stops honouring the setting.
 *
 * **Read once rather than subscribed to.** Nobody changes this setting during
 * a twelve-minute room, and a listener left attached is a leak on the screen
 * that stays open longest. The cost of being wrong is one stale read until the
 * next mount; the cost of the listener is a subscription per card on a rail of
 * eight.
 *
 * Honour it by **cutting, not by slowing**. A shortened bounce is still a
 * bounce, and the setting means "do not move things", not "move them less".
 */
export function useReduceMotion(): boolean {
  const [calm, setCalm] = useState(false);

  useEffect(() => {
    let alive = true;

    AccessibilityInfo.isReduceMotionEnabled()
      .then((on) => {
        if (alive) {
          setCalm(on);
        }
      })
      // Not knowing means moving, which is what every screen did before this
      // existed. Refusing to render over an unreadable accessibility flag
      // would be strictly worse than animating for somebody who asked us not
      // to — and the query failing at all is a platform fault, not a choice
      // they made.
      .catch(() => undefined);

    return () => {
      alive = false;
    };
  }, []);

  return calm;
}
