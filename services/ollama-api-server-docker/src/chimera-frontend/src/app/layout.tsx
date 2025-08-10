// chimera-frontend/src/app/layout.tsx
import './globals.css'
import Navbar from "@/components/Navbar";
import AuthProvider from '@/providers/SessionProvider';
import { Toaster } from "@/components/ui/sonner" // Corrected import

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body>
        <AuthProvider>
          <Navbar />
          <main className="container mx-auto p-4">{children}</main>
          <Toaster /> 
        </AuthProvider>
      </body>
    </html>
  );
}
