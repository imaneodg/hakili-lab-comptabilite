-- Sections analytiques Sage : codes sur 4 caracteres exactement.
--
-- Sage 100 impose aux numeros de section une longueur fixe, reglee a 4 dans
-- le dossier HAKILI LAB. Un code plus court est complete par des zeros
-- (PIS -> PIS0), un code plus long est tronque (TAMPOUY -> TAMP). Pour que
-- Sage n'ait jamais rien a completer ni a couper, les codes font ici
-- exactement 4 caracteres, et doivent etre identiques a ceux crees dans
-- Structure > Plan analytique.
--
-- Ne touche que la colonne section_analytique : ni le code du centre (cle
-- technique utilisee partout dans l'application), ni son intitule affiche
-- aux caissieres.

UPDATE centres SET section_analytique = 'PSSY' WHERE code_centre = 'PIS';
UPDATE centres SET section_analytique = 'TAMP' WHERE code_centre = 'TAM';
UPDATE centres SET section_analytique = 'SAAB' WHERE code_centre = 'SAA';
UPDATE centres SET section_analytique = 'SIAO' WHERE code_centre = 'SIA';
UPDATE centres SET section_analytique = 'NAGR' WHERE code_centre = 'NAG';
UPDATE centres SET section_analytique = 'SIEG' WHERE code_centre = 'SIE';

-- Controle apres coup (a jouer a la main) :
--   SELECT code_centre, intitule, section_analytique,
--          length(section_analytique) FROM centres ORDER BY code_centre;
