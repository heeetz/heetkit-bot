import type { ReactNode } from 'react'

// Sidebar section icons (24px grid, stroke follows the button text color).
const paths: Record<string, ReactNode> = {
  Dashboard: <><rect x="3.5" y="3.5" width="17" height="17" rx="2.6" /><path d="M3.5 9h17m-10 0v11.5" /></>,
  Commands: <><rect x="3.5" y="4.5" width="17" height="15" rx="2.5" /><path d="m7.5 9 3 3-3 3m6 0h3" /></>,
  Filters: <><path d="M4 4.5h16a.7.7 0 0 1 .5 1.2L14 13v5.5l-4 2V13L3.5 5.7A.7.7 0 0 1 4 4.5Z" /></>,
  AI: <><path d="M10 3.5c.9 4.7 2.3 6.1 7 7-4.7.9-6.1 2.3-7 7-.9-4.7-2.3-6.1-7-7 4.7-.9 6.1-2.3 7-7Zm8 10.5v6m-3-3h6m-2-13v4m-2-2h4" /></>,
  Logs: <><path d="M13.5 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9l-5.5-5.5Zm0 0V8a1 1 0 0 0 1 1H19M8.5 12.5h7m-7 4h7" /></>,
  Analytics: <><path d="M4 4v15a1 1 0 0 0 1 1h15M8.5 16v-4m4.7 4V8m4.8 8V5" /></>,
  Settings: <><path d="m10 3.7-.6 2.1a7 7 0 0 0-1.6.9l-2.1-.5-2 3.5 1.5 1.5a7 7 0 0 0 0 1.6l-1.5 1.5 2 3.5 2.1-.5a7 7 0 0 0 1.6.9l.6 2.1h4l.6-2.1a7 7 0 0 0 1.6-.9l2.1.5 2-3.5-1.5-1.5a7 7 0 0 0 0-1.6l1.5-1.5-2-3.5-2.1.5a7 7 0 0 0-1.6-.9L14 3.7Z" /><circle cx="12" cy="12" r="2.8" /></>,
  About: <><circle cx="12" cy="12" r="8.5" /><path d="M12 11.5v4.5m0-8h.01" /></>,
}

export default function NavIcon({ section }: { section: string }) {
  return <svg className="nav-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[section]}</svg>
}
