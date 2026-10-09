// Account, Notifications (phone-ux §6.18, plan R8): R8's push settings on their own page, reached
// from one Account row. Whether this phone is told, the three push groups, and the web for email
// and the full grid.

import { NavBar, Screen, Scroll } from '../../ui/index.tsx';
import { NotificationsSection } from '../NotificationsSection.tsx';

export default function NotificationSettingsScreen({ onBack }: { onBack: () => void }) {
  return (
    <Screen>
      <NavBar onBack={onBack} title="Notifications" />
      <Scroll>
        <NotificationsSection titled={false} />
      </Scroll>
    </Screen>
  );
}
