/** Inline icon set — kept local so the app ships no icon-font dependency. */
export type IconName =
  | 'menu' | 'search' | 'send' | 'attach' | 'close' | 'back' | 'more'
  | 'check' | 'checkDouble' | 'clock' | 'alert' | 'pin' | 'mute' | 'bell'
  | 'settings' | 'user' | 'users' | 'megaphone' | 'file' | 'download'
  | 'trash' | 'reply' | 'copy' | 'logout' | 'moon' | 'sun' | 'edit';

const PATHS: Record<IconName, string> = {
  menu: 'M4 7h16M4 12h16M4 17h16',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4',
  send: 'M4 12l16-8-6 8 6 8-16-8z',
  attach: 'M20 11l-8 8a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8',
  close: 'M6 6l12 12M18 6L6 18',
  back: 'M15 5l-7 7 7 7',
  more: 'M12 6h.01M12 12h.01M12 18h.01',
  check: 'M4 12l5 5L20 6',
  checkDouble: 'M1 12l5 5L15 6M10 15l2 2L23 6',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2',
  alert: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 8v5M12 16h.01',
  pin: 'M9 4h6l-1 6 4 3v2H6v-2l4-3-1-6zM12 15v5',
  mute: 'M6 9a6 6 0 0 1 12 0v5l2 3H4l2-3V9zM4 4l16 16',
  bell: 'M6 9a6 6 0 0 1 12 0v5l2 3H4l2-3V9zM10 20a2 2 0 0 0 4 0',
  settings: 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM4 12h2M18 12h2M12 4v2M12 18v2M6.3 6.3l1.4 1.4M16.3 16.3l1.4 1.4M17.7 6.3l-1.4 1.4M7.7 16.3l-1.4 1.4',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 20c0-3.3 3.6-6 8-6s8 2.7 8 6',
  users: 'M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2 20c0-3 3.1-5.5 7-5.5s7 2.5 7 5.5M17 11a3 3 0 1 0 0-6M18 20c0-2.2-.9-4-2.4-5.2',
  megaphone: 'M4 10v4h3l7 4V6l-7 4H4zM18 9a4 4 0 0 1 0 6',
  file: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5zM14 3v5h5',
  download: 'M12 4v11M7 12l5 5 5-5M5 20h14',
  trash: 'M5 7h14M10 7V5h4v2M6 7l1 13h10l1-13',
  reply: 'M9 7L4 12l5 5M4 12h9a7 7 0 0 1 7 7',
  copy: 'M9 9h10v10H9zM5 15V5h10',
  logout: 'M14 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8M16 12H9M19 12l-4-4M19 12l-4 4',
  moon: 'M20 14a8 8 0 1 1-10-10 7 7 0 0 0 10 10z',
  sun: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19',
  edit: 'M4 20h4l10-10-4-4L4 16v4zM14 6l4 4',
};

interface IconProps {
  name: IconName;
  size?: number;
  className?: string;
}

export function Icon({ name, size = 20, className }: IconProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
