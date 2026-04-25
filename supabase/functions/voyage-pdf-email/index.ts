// @ts-nocheck
import { serve } from 'https://deno.land/std@0.224.0/http/server.ts';

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS'
};

serve(async req => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders });
  }

  if (req.method !== 'POST') {
    return new Response(JSON.stringify({ error: 'Method not allowed' }), {
      status: 405,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }

  const resendApiKey = Deno.env.get('RESEND_API_KEY');
  const fromEmail = Deno.env.get('RESEND_FROM_EMAIL') || Deno.env.get('VOYAGE_EMAIL_FROM');
  if (!resendApiKey || !fromEmail) {
    return new Response(JSON.stringify({ error: 'Missing RESEND_API_KEY or RESEND_FROM_EMAIL secret' }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }

  try {
    const body = await req.json();
    const to = Array.isArray(body?.to) ? body.to.map(value => String(value || '').trim()).filter(Boolean) : [];
    const cc = Array.isArray(body?.cc) ? body.cc.map(value => String(value || '').trim()).filter(Boolean) : [];
    const replyTo = String(body?.replyTo || '').trim();
    const subject = String(body?.subject || '').trim();
    const html = String(body?.html || '').trim();
    const text = String(body?.text || '').trim();
    const attachmentName = String(body?.attachment?.filename || '').trim();
    const attachmentContentBase64 = String(body?.attachment?.contentBase64 || '').trim();
    const attachmentContentType = String(body?.attachment?.contentType || 'application/pdf').trim();

    if (!to.length || !subject || (!html && !text) || !attachmentName || !attachmentContentBase64) {
      return new Response(JSON.stringify({ error: 'Missing to, subject, html/text, or attachment fields' }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const resendPayload = {
      from: fromEmail,
      to,
      ...(cc.length ? { cc } : {}),
      ...(replyTo ? { reply_to: [replyTo] } : {}),
      subject,
      ...(html ? { html } : {}),
      ...(text ? { text } : {}),
      attachments: [
        {
          filename: attachmentName,
          content: attachmentContentBase64,
          type: attachmentContentType
        }
      ]
    };

    const resendResponse = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${resendApiKey}`
      },
      body: JSON.stringify(resendPayload)
    });

    const payload = await resendResponse.json().catch(() => ({}));
    if (!resendResponse.ok) {
      return new Response(JSON.stringify(payload), {
        status: resendResponse.status,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    return new Response(JSON.stringify({ ok: true, result: payload }), {
      status: 200,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: String(error?.message || error) }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
});