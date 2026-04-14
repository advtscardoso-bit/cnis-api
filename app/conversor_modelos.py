"""
Conversor dict → Pydantic: transforma a saída do cnis_parser.py e dados do
formulário de entrevista em modelos Pydantic tipados e validados.

FLUXO:
    parse_cnis(pdf) → dict          (cnis_parser.py — já existe)
    parse_formulario(pdf) → dict    (formulario_parser.py — novo)
    converter(dict_cnis, dict_form) → DadosConvertidos  (ESTE MÓDULO)

O conversor é o PONTO DE INTEGRAÇÃO entre o parser (texto bruto → dict) e
o pipeline de análise/classificação (Pydantic → regras de negócio).
"""

import json
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from app.models.pessoa import Pessoa, Sexo
from app.models.vinculo import Vinculo, TipoVinculo, SituacaoVinculo, AliquotaContribuicao
from app.models.contribuicao import Contribuicao, TipoContribuicao
from app.models.beneficio import Beneficio, EspecieBeneficio
from app.models.indicador import (
    IndicadorCNIS, ClassificacaoIndicador, SeveridadeIndicador,
)
from app.models.formulario import DadosFormulario

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent / "config"


# ============================================================================
#  RESULTADO DA CONVERSÃO
# ============================================================================

class DadosConvertidos(BaseModel):
    """Resultado completo da conversão dict → Pydantic."""
    pessoa: Pessoa
    vinculos: list[Vinculo]
    contribuicoes: list[Contribuicao]
    beneficios: list[Beneficio]
    indicadores: list[IndicadorCNIS]
    formulario: Optional[DadosFormulario] = None
    avisos: list[str] = Field(default_factory=list)


# ============================================================================
#  CARREGAMENTO DE CONFIGURAÇÕES
# ============================================================================

def _carregar_indicadores_json() -> dict:
    """Carrega dicionário de indicadores."""
    caminho = CONFIG_DIR / "indicadores_cnis.json"
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def _carregar_salarios_minimos() -> list[dict]:
    """Carrega tabela de salários mínimos."""
    caminho = CONFIG_DIR / "tabela_salario_minimo.json"
    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)
    return dados["salarios_minimos"]


def _obter_sm_competencia(competencia: str, tabela_sm: list[dict]) -> Optional[Decimal]:
    """Retorna SM vigente na competência (MM/AAAA) como Decimal."""
    try:
        mes, ano = competencia.split("/")
        data_comp = date(int(ano), int(mes), 1)
    except (ValueError, AttributeError):
        return None

    for entrada in tabela_sm:
        data_vigencia = date.fromisoformat(entrada["vigencia"])
        if data_vigencia <= data_comp:
            return Decimal(str(entrada["valor"]))
    return None


def _carregar_tetos_rgps() -> list[dict]:
    """Carrega tabela de tetos do RGPS."""
    caminho = CONFIG_DIR / "tetos_rgps.json"
    if not caminho.exists():
        return []
    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)
    return dados if isinstance(dados, list) else dados.get("tetos", [])


def _obter_teto_competencia(competencia: str, tabela_tetos: list[dict]) -> Optional[Decimal]:
    """Retorna o teto RGPS vigente na competência."""
    try:
        mes, ano = competencia.split("/")
        data_comp = date(int(ano), int(mes), 1)
    except (ValueError, AttributeError):
        return None

    for entrada in tabela_tetos:
        data_vigencia = date.fromisoformat(entrada.get("vigencia", "1900-01-01"))
        if data_vigencia <= data_comp:
            return Decimal(str(entrada["valor"]))
    return None


# ============================================================================
#  CONVERSÃO DE TIPOS BÁSICOS
# ============================================================================

def _parse_data(valor: Optional[str]) -> Optional[date]:
    """Converte string DD/MM/AAAA em date. Retorna None se inválido."""
    if not valor:
        return None
    try:
        return datetime.strptime(valor.strip(), "%d/%m/%Y").date()
    except ValueError:
        logger.warning("Data inválida: %s", valor)
        return None


def _parse_decimal(valor) -> Decimal:
    """Converte valor (str, float, int, None) em Decimal."""
    if valor is None:
        return Decimal("0")
    if isinstance(valor, Decimal):
        return valor
    try:
        if isinstance(valor, str):
            valor_str = valor.strip()
            if "," in valor_str:
                # Formato BR: "1.234,56" → "1234.56"
                valor_str = valor_str.replace(".", "").replace(",", ".")
            # Se não tem vírgula, é formato internacional (450.00)
            return Decimal(valor_str)
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        logger.warning("Valor monetário inválido: %s", valor)
        return Decimal("0")


def _limpar_cpf(cpf: Optional[str]) -> str:
    """Remove formatação do CPF."""
    if not cpf:
        return ""
    return "".join(c for c in cpf if c.isdigit())


# ============================================================================
#  MAPEAMENTO: tipo string do parser → TipoVinculo enum
# ============================================================================

_MAPA_TIPO_VINCULO = {
    "Empregado": TipoVinculo.CLT,
    "Empregado Doméstico": TipoVinculo.EMPREGADO_DOMESTICO,
    "Contribuinte Individual": TipoVinculo.CONTRIBUINTE_INDIVIDUAL,
    "Segurado Especial": TipoVinculo.RURAL_SEGURADO_ESPECIAL,
    "Trabalhador Avulso": TipoVinculo.CLT,  # Avulso → CLT para fins de cálculo
    "Agente Público": TipoVinculo.SERVIDOR_PUBLICO,
    "Facultativo": TipoVinculo.FACULTATIVO,
    "Microempreendedor Individual": TipoVinculo.MEI,
    "Não identificado": TipoVinculo.DESCONHECIDO,
}


def _mapear_tipo_vinculo(tipo_str: str) -> TipoVinculo:
    """Converte a string do tipo do parser para o enum TipoVinculo."""
    resultado = _MAPA_TIPO_VINCULO.get(tipo_str)
    if resultado is None:
        logger.warning("Tipo de vínculo não mapeado: '%s' → DESCONHECIDO", tipo_str)
        return TipoVinculo.DESCONHECIDO
    return resultado


# ============================================================================
#  MAPEAMENTO: espécie string do parser → EspecieBeneficio enum
# ============================================================================

_MAPA_ESPECIE_BENEFICIO = {
    "41": EspecieBeneficio.B41,
    "42": EspecieBeneficio.B42,
    "46": EspecieBeneficio.B46,
    "57": EspecieBeneficio.B57,
    "31": EspecieBeneficio.B31,
    "32": EspecieBeneficio.B32,
    "91": EspecieBeneficio.B91,
    "92": EspecieBeneficio.B92,
    "94": EspecieBeneficio.B94,
    "87": EspecieBeneficio.B87,
    "36": EspecieBeneficio.B36,
    "21": EspecieBeneficio.B21,
    "93": EspecieBeneficio.B93,
    "80": EspecieBeneficio.B80,
    "25": EspecieBeneficio.B25,
    "88": EspecieBeneficio.B88,
}


def _mapear_especie_beneficio(especie_str: Optional[str]) -> EspecieBeneficio:
    """Extrai código numérico da espécie e mapeia para enum."""
    if not especie_str:
        return EspecieBeneficio.OUTRO
    # especie_str vem como "31 - Auxílio-doença previdenciário"
    codigo = especie_str.strip().split()[0].split("-")[0].strip()
    return _MAPA_ESPECIE_BENEFICIO.get(codigo, EspecieBeneficio.OUTRO)


# ============================================================================
#  CLASSIFICAÇÃO DE INDICADORES → Pydantic
# ============================================================================

def _classificar_indicador(codigo: str, dicionario: dict) -> IndicadorCNIS:
    """Classifica um código de indicador usando o dicionário JSON."""
    # Buscar em pendências
    if codigo in dicionario.get("PENDENCIAS", {}):
        info = dicionario["PENDENCIAS"][codigo]
        return IndicadorCNIS(
            codigo=codigo,
            classificacao=ClassificacaoIndicador.PENDENCIA,
            severidade=_inferir_severidade_pendencia(codigo),
            nome=info.get("nome", ""),
            descricao=info.get("descricao", ""),
            impacto=info.get("impacto", ""),
            acao=info.get("acao", ""),
        )

    # Buscar em alertas
    if codigo in dicionario.get("ALERTAS", {}):
        info = dicionario["ALERTAS"][codigo]
        return IndicadorCNIS(
            codigo=codigo,
            classificacao=ClassificacaoIndicador.ALERTA,
            severidade=SeveridadeIndicador.MEDIA,
            nome=info.get("nome", ""),
            descricao=info.get("descricao", ""),
            impacto=info.get("impacto", ""),
            acao=info.get("acao", ""),
        )

    # Buscar em acertos
    if codigo in dicionario.get("ACERTOS", {}):
        info = dicionario["ACERTOS"][codigo]
        return IndicadorCNIS(
            codigo=codigo,
            classificacao=ClassificacaoIndicador.ACERTO,
            severidade=SeveridadeIndicador.INFORMATIVA,
            nome=info.get("nome", ""),
            descricao=info.get("descricao", ""),
            impacto=info.get("impacto", ""),
            acao=info.get("acao", ""),
        )

    # REGRA SYS-02: Desconhecido — NUNCA inventar significado
    logger.warning("Indicador desconhecido: %s — classificado como DESCONHECIDO", codigo)
    return IndicadorCNIS(
        codigo=codigo,
        classificacao=ClassificacaoIndicador.DESCONHECIDO,
        severidade=SeveridadeIndicador.MEDIA,
        nome=f"Indicador não catalogado: {codigo}",
        descricao="Este indicador não consta no dicionário do sistema.",
        impacto="Impacto desconhecido — requer análise manual.",
        acao="Consultar o INSS ou jurisprudência para significado deste indicador.",
    )


# Indicadores de pendência com severidade crítica (bloqueiam cômputo)
_INDICADORES_CRITICOS = {
    "PREM-BLOQ-EC103", "PREC-MENOR-MIN", "PREC-MENORMIN",
    "PSC-MEN-SM-EC103",
}

# Indicadores de pendência com severidade alta
_INDICADORES_ALTA = {
    "PEXT", "PADM-EMPR", "PRES-EMPR", "PREM-EXT", "PREM-EMPR",
    "PDIV-DADOS-GFIP", "PMOV-INCONSIST",
}


def _inferir_severidade_pendencia(codigo: str) -> SeveridadeIndicador:
    """Infere severidade de uma pendência pelo código."""
    if codigo in _INDICADORES_CRITICOS:
        return SeveridadeIndicador.CRITICA
    if codigo in _INDICADORES_ALTA:
        return SeveridadeIndicador.ALTA
    return SeveridadeIndicador.MEDIA


# ============================================================================
#  CONVERSÃO PRINCIPAL: dict CNIS + dict Formulário → DadosConvertidos
# ============================================================================

def converter(
    resultado_parser: dict,
    dados_formulario: Optional[dict] = None,
) -> DadosConvertidos:
    """
    Converte o resultado do cnis_parser + dados do formulário em modelos Pydantic.

    Args:
        resultado_parser: dict retornado por cnis_parser.parse_cnis()
        dados_formulario: dict com dados do formulário de entrevista (opcional)

    Returns:
        DadosConvertidos com todos os modelos Pydantic populados

    Raises:
        ValueError: se resultado_parser não tem sucesso ou dados essenciais faltam
    """
    if not resultado_parser.get("sucesso"):
        raise ValueError(f"Parser retornou erro: {resultado_parser.get('erro')}")

    dados = resultado_parser["dados"]
    cabecalho = dados["cabecalho"]
    vinculos_raw = dados["vinculos"]

    avisos: list[str] = []

    # Carregar configurações
    dicionario_indicadores = _carregar_indicadores_json()
    tabela_sm = _carregar_salarios_minimos()
    tabela_tetos = _carregar_tetos_rgps()

    # ── Formulário (se fornecido) ──
    formulario = None
    if dados_formulario:
        try:
            formulario = DadosFormulario(**dados_formulario)
        except Exception as e:
            avisos.append(f"Erro ao processar formulário: {e}")
            logger.warning("Falha ao criar DadosFormulario: %s", e)

    # ── Pessoa ──
    pessoa = _converter_pessoa(cabecalho, formulario, avisos)

    # ── Vínculos + Contribuições + Benefícios ──
    vinculos: list[Vinculo] = []
    contribuicoes: list[Contribuicao] = []
    beneficios: list[Beneficio] = []
    todos_indicadores_codigos: set[str] = set()

    for v_raw in vinculos_raw:
        if v_raw.get("eh_beneficio"):
            beneficio = _converter_beneficio(v_raw, avisos)
            if beneficio:
                beneficios.append(beneficio)
                # Contribuições do período de benefício também
                contribs = _converter_remuneracoes(
                    v_raw, tabela_sm, tabela_tetos, avisos
                )
                contribuicoes.extend(contribs)
        else:
            vinculo = _converter_vinculo(v_raw, avisos)
            if vinculo:
                vinculos.append(vinculo)
                contribs = _converter_remuneracoes(
                    v_raw, tabela_sm, tabela_tetos, avisos
                )
                contribuicoes.extend(contribs)

        # Coletar indicadores
        todos_indicadores_codigos.update(v_raw.get("indicadores_vinculo", []))
        for rem in v_raw.get("remuneracoes", []):
            todos_indicadores_codigos.update(rem.get("indicadores", []))

    # ── Indicadores ──
    indicadores = _converter_indicadores(
        todos_indicadores_codigos, vinculos_raw, dicionario_indicadores
    )

    logger.info(
        "Conversão concluída: %s — %d vínculos, %d contribuições, "
        "%d benefícios, %d indicadores, %d avisos",
        pessoa.nome,
        len(vinculos),
        len(contribuicoes),
        len(beneficios),
        len(indicadores),
        len(avisos),
    )

    return DadosConvertidos(
        pessoa=pessoa,
        vinculos=vinculos,
        contribuicoes=contribuicoes,
        beneficios=beneficios,
        indicadores=indicadores,
        formulario=formulario,
        avisos=avisos,
    )


# ============================================================================
#  CONVERSORES INDIVIDUAIS
# ============================================================================

def _converter_pessoa(
    cabecalho: dict,
    formulario: Optional[DadosFormulario],
    avisos: list[str],
) -> Pessoa:
    """
    Converte cabeçalho CNIS + formulário → Pessoa.

    O CNIS NÃO contém o sexo do segurado. O sexo DEVE vir do formulário.
    Sem sexo, é impossível calcular regras de aposentadoria.
    """
    # CPF: vem exclusivamente do CNIS (documento oficial)
    cpf = _limpar_cpf(cabecalho.get("cpf"))

    # Nome: CNIS é referência, formulário pode complementar
    nome = cabecalho.get("nome", "")
    if not nome and formulario:
        nome = formulario.nome_completo

    # Data de nascimento: CNIS é referência
    data_nasc = _parse_data(cabecalho.get("data_nascimento"))
    if data_nasc is None and formulario:
        data_nasc = formulario.data_nascimento

    # Sexo: SÓ pode vir do formulário (CNIS não tem esse campo)
    sexo = None
    if formulario:
        sexo = Sexo.MASCULINO if formulario.sexo == "M" else Sexo.FEMININO
    else:
        avisos.append(
            "CRÍTICO: Sexo do segurado não informado (formulário ausente). "
            "Todas as regras de aposentadoria dependem do sexo. "
            "Usando MASCULINO como fallback — VERIFICAR MANUALMENTE."
        )
        sexo = Sexo.MASCULINO  # Fallback conservador (requisitos mais altos)

    if not cpf:
        raise ValueError("CPF não encontrado no CNIS nem no formulário")
    if not nome:
        raise ValueError("Nome não encontrado no CNIS nem no formulário")
    if data_nasc is None:
        raise ValueError("Data de nascimento não encontrada no CNIS nem no formulário")

    return Pessoa(
        cpf=cpf,
        nome=nome.strip(),
        data_nascimento=data_nasc,
        sexo=sexo,
        nit=cabecalho.get("nit"),
        nome_mae=cabecalho.get("nome_mae"),
        data_emissao_cnis=_parse_data(cabecalho.get("data_emissao")),
    )


def _converter_vinculo(v_raw: dict, avisos: list[str]) -> Optional[Vinculo]:
    """Converte um dict de vínculo do parser → Vinculo Pydantic."""
    data_inicio = _parse_data(v_raw.get("data_inicio"))
    if data_inicio is None:
        avisos.append(
            f"Vínculo seq={v_raw.get('seq')} sem data de início — ignorado"
        )
        return None

    data_fim = _parse_data(v_raw.get("data_fim"))

    tipo = _mapear_tipo_vinculo(v_raw.get("tipo", "Não identificado"))

    # Situação: se tem data_fim → ENCERRADO, senão ATIVO
    situacao = SituacaoVinculo.ENCERRADO if data_fim else SituacaoVinculo.ATIVO

    return Vinculo(
        sequencia=v_raw.get("seq"),
        tipo=tipo,
        situacao=situacao,
        empregador=v_raw.get("empregador"),
        cnpj_cei=v_raw.get("identificador_empregador"),
        data_inicio=data_inicio,
        data_fim=data_fim,
        indicadores=v_raw.get("indicadores_vinculo", []),
        origem="CNIS",
    )


def _converter_beneficio(v_raw: dict, avisos: list[str]) -> Optional[Beneficio]:
    """Converte um dict de benefício do parser → Beneficio Pydantic."""
    data_inicio = _parse_data(v_raw.get("data_inicio"))
    if data_inicio is None:
        avisos.append(
            f"Benefício NB={v_raw.get('numero_beneficio')} sem DIB — ignorado"
        )
        return None

    data_fim = _parse_data(v_raw.get("data_fim"))
    especie = _mapear_especie_beneficio(v_raw.get("especie_beneficio"))

    return Beneficio(
        especie=especie,
        nb=v_raw.get("numero_beneficio"),
        dib=data_inicio,
        dcb=data_fim,
        indicadores=v_raw.get("indicadores_vinculo", []),
    )


def _converter_remuneracoes(
    v_raw: dict,
    tabela_sm: list[dict],
    tabela_tetos: list[dict],
    avisos: list[str],
) -> list[Contribuicao]:
    """Converte remunerações de um vínculo → lista de Contribuicao Pydantic."""
    contribuicoes = []
    seq = v_raw.get("seq")

    for rem in v_raw.get("remuneracoes", []):
        competencia = rem.get("competencia")
        if not competencia:
            continue

        valor = _parse_decimal(rem.get("valor"))
        indicadores = rem.get("indicadores", [])

        # Obter SM e teto da competência
        sm = _obter_sm_competencia(competencia, tabela_sm)
        teto = _obter_teto_competencia(competencia, tabela_tetos)

        # Detectar flags por indicadores
        indicadores_set = set(indicadores)
        abaixo_minimo = bool(
            indicadores_set & {"PREC-MENOR-MIN", "PREC-MENORMIN", "PSC-MEN-SM-EC103"}
        )
        bloqueada = "PREM-BLOQ-EC103" in indicadores_set
        extemporanea = "PREM-EXT" in indicadores_set

        # Se não detectado por indicador, verificar pelo valor vs SM
        if not abaixo_minimo and sm and valor > Decimal("0") and valor < sm:
            abaixo_minimo = True

        contribuicoes.append(
            Contribuicao(
                competencia=competencia,
                vinculo_sequencia=seq,
                valor_original=valor,
                indicadores=indicadores,
                abaixo_minimo=abaixo_minimo,
                bloqueada=bloqueada,
                extemporanea=extemporanea,
                sm_competencia=sm,
                teto_competencia=teto,
            )
        )

    return contribuicoes


def _converter_indicadores(
    codigos: set[str],
    vinculos_raw: list[dict],
    dicionario: dict,
) -> list[IndicadorCNIS]:
    """Converte todos os códigos de indicadores encontrados → IndicadorCNIS."""
    indicadores = []

    for codigo in sorted(codigos):
        indicador = _classificar_indicador(codigo, dicionario)

        # Encontrar competências e vínculos afetados
        competencias_afetadas = set()
        vinculos_afetados = set()

        for v in vinculos_raw:
            if codigo in v.get("indicadores_vinculo", []):
                vinculos_afetados.add(v.get("seq"))
            for rem in v.get("remuneracoes", []):
                if codigo in rem.get("indicadores", []):
                    competencias_afetadas.add(rem.get("competencia"))
                    vinculos_afetados.add(v.get("seq"))

        indicador.competencias_afetadas = sorted(competencias_afetadas)
        if vinculos_afetados:
            # Usar o primeiro vínculo associado (simplificação)
            indicador.vinculo_sequencia = min(v for v in vinculos_afetados if v is not None)

        indicadores.append(indicador)

    return indicadores
