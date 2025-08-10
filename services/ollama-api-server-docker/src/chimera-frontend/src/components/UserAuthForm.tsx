'use client';

import * as React from 'react';
import { signIn } from 'next-auth/react';
import { useSearchParams, useRouter } from 'next/navigation';
import { toast } from "sonner"; 

// import { cn } from '@/lib/utils'; // Unused import removed
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"


export function UserAuthForm() {
  const router = useRouter();
  const [isLoading, setIsLoading] = React.useState<boolean>(false);

  const [loginEmail, setLoginEmail] = React.useState('');
  const [loginPassword, setLoginPassword] = React.useState('');

  const [registerEmail, setRegisterEmail] = React.useState('');
  const [registerPassword, setRegisterPassword] = React.useState('');
  const [registerConfirmPassword, setRegisterConfirmPassword] = React.useState('');

  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get('callbackUrl') || '/dashboard';

  async function handleLogin(event: React.SyntheticEvent) {
    event.preventDefault();
    setIsLoading(true);

    const result = await signIn('credentials', {
      redirect: false,
      email: loginEmail,
      password: loginPassword,
    });

    setIsLoading(false);

    if (result?.error) {
       toast.error("Login Failed", { description: result.error });
    } else {
      toast.success("Login Successful");
      router.push(callbackUrl);
    }
  }

  async function handleRegister(event: React.SyntheticEvent) {
    event.preventDefault();
    if (registerPassword !== registerConfirmPassword) {
      toast.error("Registration Failed", { description: "Passwords do not match." });
      return;
    }
    setIsLoading(true);

    try {
      const response = await fetch('/api/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: registerEmail, password: registerPassword }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.message || 'Something went wrong');
      }

      toast.success("Registration Successful", {
        description: "Please log in with your new account.",
      });

    } catch (error) {
        if (error instanceof Error) {
            toast.error("Registration Failed", { description: error.message });
        } else {
            toast.error("Registration Failed", { description: "An unknown error occurred." });
        }
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <Tabs defaultValue="login" className="w-[400px]">
      <TabsList className="grid w-full grid-cols-2">
        <TabsTrigger value="login">Login</TabsTrigger>
        <TabsTrigger value="register">Register</TabsTrigger>
      </TabsList>
      <TabsContent value="login">
        <Card>
          <CardHeader>
            <CardTitle>Login</CardTitle>
            <CardDescription>Enter your credentials to access your account.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleLogin}>
              <div className="grid gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="login-email">Email</Label>
                  <Input id="login-email" type="email" value={loginEmail} onChange={e => setLoginEmail(e.target.value)} required disabled={isLoading} />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="login-password">Password</Label>
                  <Input id="login-password" type="password" value={loginPassword} onChange={e => setLoginPassword(e.target.value)} required disabled={isLoading} />
                </div>
                <Button disabled={isLoading}>
                  {isLoading ? 'Signing In...' : 'Sign In'}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </TabsContent>
      <TabsContent value="register">
        <Card>
          <CardHeader>
            <CardTitle>Register</CardTitle>
            <CardDescription>Create a new account to get started.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleRegister}>
              <div className="grid gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="register-email">Email</Label>
                  <Input id="register-email" type="email" value={registerEmail} onChange={e => setRegisterEmail(e.target.value)} required disabled={isLoading} />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="register-password">Password</Label>
                  <Input id="register-password" type="password" value={registerPassword} onChange={e => setRegisterPassword(e.target.value)} required disabled={isLoading} />
                </div>
                 <div className="grid gap-2">
                  <Label htmlFor="confirm-password">Confirm Password</Label>
                  <Input id="confirm-password" type="password" value={registerConfirmPassword} onChange={e => setRegisterConfirmPassword(e.target.value)} required disabled={isLoading} />
                </div>
                <Button disabled={isLoading}>
                  {isLoading ? 'Registering...' : 'Register'}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  );
}
