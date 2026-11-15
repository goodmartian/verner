import { screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { renderI18n } from '../test/render';
import { makeConfig } from '../test/configFixtures';
import { ApiError } from './client';
import { useApiErrorText } from './useApiErrorText';

it('uses config country names in the current UI language for not_covered', () => {
  localStorage.setItem('senda-lang', 'ru');
  const config = makeConfig();
  function Probe() {
    return <p>{useApiErrorText()(new ApiError(409, 'not_covered', 'server text'))}</p>;
  }
  renderI18n(<Probe />, config);
  expect(screen.getByText(/Страны с охватом:/)).toHaveTextContent(
    config.countries[0]?.names.ru ?? '',
  );
  expect(screen.queryByText('server text')).not.toBeInTheDocument();
});

it('says in minutes how long a refused question has to wait', () => {
  localStorage.setItem('senda-lang', 'ru');
  function Probe() {
    const text = useApiErrorText();
    return (
      <>
        <p>{text(new ApiError(429, 'chat_quota', 'x', [], 61))}</p>
        <p>{text(new ApiError(429, 'chat_banned', 'x', [], 600))}</p>
        <p>{text(new ApiError(429, 'chat_quota', 'x'))}</p>
      </>
    );
  }
  renderI18n(<Probe />, makeConfig());
  expect(screen.getByText('Слишком много вопросов. Попробуйте через 2 мин.')).toBeInTheDocument();
  expect(screen.getByText(/^Чат закрыт на 10 мин: /)).toBeInTheDocument();
  expect(screen.getByText('Слишком много вопросов. Попробуйте через 1 мин.')).toBeInTheDocument();
});
