import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Factory Traffic Management System | CSI Smart Tech',
  description: 'Industrial IoT Traffic Control Dashboard for Garment Manufacturing Facility',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
