# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python 3.12, FastAPI with server-rendered Jinja2 HTML and plain CSS, deployed on Vercel (user decision, 2026-11-15). Streamlit was the original ask but was dropped because Vercel's serverless runtime can't hold Streamlit sessions. No JavaScript application code. Small progressive enhancements are allowed only where a page truly needs one.

## Users

- **Households in India**, starting with the Thakurli, Dombivli and Kalyan pilot (Maharashtra). Someone at home with an item in hand who wants to know which bin it goes in, whether it's dangerous, or whether someone could use it.
- **Housing-society coordinators** who organise segregation and collection drives for many flats.
- **NGOs and donation organisations** who receive usable items and need listings that match what they actually accept.
- **Recycling partners** (e-waste handlers, scrap dealers, collection centres) who want to be found.
- **Community volunteers** who help with pickups and spread the word.
- **Admins** who moderate listings, verify partners and review flagged AI answers.

Phone and desktop matter equally. Households mostly use phones, often on mobile data. Coordinators, NGOs and admins often use desktops.

## Product Purpose

Help people in India dispose of household waste correctly and give usable items a second life. The product identifies an item from a photo, explains how to segregate it, gives safe disposal steps, points to recycling facilities, and connects donors with verified organisations. Success means fewer items wrongly binned, hazardous waste handled safely, and more usable items reaching people who need them.

## Positioning

RELOOP AI joins three jobs that live apart today: "which bin does this go in", "is this dangerous", and "who would take this". It answers them from one photo, using Indian rules and local partners. Its answers are grounded in documents it has actually loaded, it says plainly when it doesn't know, and it never invents an NGO, a rule or a certainty level.

## Operating Context

- Indian municipal segregation: wet and dry waste, plus separate streams for e-waste, household hazardous waste, sanitary/biomedical waste and textiles.
- Locality and PIN-code based search. Kalyan-Dombivli Municipal Corporation (KDMC) area for the pilot.
- Donation coordination: a listing, then a request, then donor approval, then pickup or handover. No public phone numbers, emails or precise addresses.
- Admin moderation queue for listings, partner verification and flagged AI responses.

## Capabilities and Constraints

- Waste categories: wet, dry recyclable, e-waste, household hazardous, medical/biomedical, textile, reusable/donatable, other/uncertain.
- Donation categories: clothes, books, toys, furniture, electronics, school supplies, household goods, other reusable items.
- Listing statuses: Pending Review, Available, Reserved, Completed, Rejected.
- AI certainty is shown as a qualitative level, never a made-up percentage. The AI never assumes an item works or is clean or safe from a photo, and always asks the user to confirm its condition.
- The RAG assistant answers only from ingested documents and says so when it has nothing. The knowledge base starts empty.
- Directory entries from external search are "unverified" until an admin verifies them.
- No carbon or impact figures without a documented method.
- Hazardous and medical waste can never be listed as a donation.
- **Language:** English for the MVP. All interface text lives in one place so Hindi and Marathi can be added later.

## Brand Commitments

- Name: **RELOOP AI**. Tagline: **Sort Smart. Reuse More. Waste Less.**
- Homepage headline: **"Don't Throw It Away. Give It a Better Way."**
- Visual constraints from the brief: white backgrounds, forest-green accents, soft neutral surfaces, professional typography, rounded cards, consistent spacing, lightweight, no unnecessary animation.
- No logo exists yet. A wordmark and mark will be designed and can be replaced later.
- Voice: plain, practical English for Indian households. No jargon and no guilt-tripping.

## Evidence on Hand

- No logo, photography, partner list, testimonials, usage numbers or impact data exist yet.
- No confirmed NGO or recycling partners. Directory and donation content must be empty or clearly labelled demonstration data.
- No official documents ingested yet. Never cite regulations, documents or URLs that aren't actually in the knowledge base.

## Product Principles

1. **Safety before convenience.** When an item might be hazardous or the AI is unsure, ask first and warn clearly.
2. **Honest about what it knows.** Cite real sources, show uncertainty in words, and say "we don't know yet" instead of guessing.
3. **Local and specific.** Answers point to a locality, a PIN code, a real collection point, a real organisation.
4. **Reuse first.** Before disposal, check whether something can be repaired, reused or donated.
5. **Privacy by default.** Donors stay reachable without exposing their phone, email or home.

## Accessibility & Inclusion

WCAG 2.2 AA. Readable on low-end Android phones and slow connections: light pages, large tap targets, plain language suited to readers with varying English fluency.
