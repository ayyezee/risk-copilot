import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '../components/ui/card';
import { Shield, Loader2, Copy, Check } from 'lucide-react';

export function Setup2FA() {
  const navigate = useNavigate();
  const [code, setCode] = useState('');
  const [copied, setCopied] = useState(false);
  const {
    user,
    setup2FA,
    enable2FA,
    isSettingUp2FA,
    setup2FAData,
    setup2FAError,
  } = useAuth();

  useEffect(() => {
    if (!user?.totp_enabled) {
      setup2FA();
    }
  }, [user, setup2FA]);

  const handleCopySecret = async () => {
    if (setup2FAData?.secret) {
      await navigator.clipboard.writeText(setup2FAData.secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await enable2FA(code);
      navigate('/documents');
    } catch (error) {
      // Error is handled by the mutation
    }
  };

  const handleSkip = () => {
    navigate('/documents');
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 to-slate-800 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1 text-center">
          <div className="flex justify-center mb-4">
            <div className="p-3 bg-primary/10 rounded-full">
              <Shield className="h-8 w-8 text-primary" />
            </div>
          </div>
          <CardTitle className="text-2xl font-bold">
            Set up Two-Factor Authentication
          </CardTitle>
          <CardDescription>
            Add an extra layer of security to your account
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            {setup2FAError && (
              <div className="p-3 text-sm text-red-500 bg-red-50 border border-red-200 rounded-md">
                {(setup2FAError as Error).message || 'Failed to set up 2FA'}
              </div>
            )}

            {isSettingUp2FA ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
              </div>
            ) : setup2FAData ? (
              <>
                <div className="space-y-4">
                  <p className="text-sm text-muted-foreground">
                    Scan this QR code with your authenticator app (Google
                    Authenticator, Authy, etc.)
                  </p>

                  <div className="flex justify-center p-4 bg-white rounded-lg">
                    <img
                      src={setup2FAData.qr_code}
                      alt="2FA QR Code"
                      className="w-48 h-48"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label className="text-xs text-muted-foreground">
                      Or enter this secret manually:
                    </Label>
                    <div className="flex items-center space-x-2">
                      <code className="flex-1 p-2 bg-muted rounded text-xs font-mono break-all">
                        {setup2FAData.secret}
                      </code>
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        onClick={handleCopySecret}
                      >
                        {copied ? (
                          <Check className="h-4 w-4 text-green-500" />
                        ) : (
                          <Copy className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="code">Verification Code</Label>
                  <Input
                    id="code"
                    type="text"
                    placeholder="Enter 6-digit code"
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    maxLength={6}
                    pattern="\d{6}"
                    required
                    autoComplete="one-time-code"
                    className="text-center text-lg tracking-widest"
                  />
                </div>
              </>
            ) : null}
          </CardContent>
          <CardFooter className="flex flex-col space-y-2">
            <Button
              type="submit"
              className="w-full"
              disabled={isSettingUp2FA || code.length !== 6}
            >
              Enable 2FA
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="w-full"
              onClick={handleSkip}
            >
              Skip for now
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
